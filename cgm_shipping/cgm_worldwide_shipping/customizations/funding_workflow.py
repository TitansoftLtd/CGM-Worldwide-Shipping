# Copyright (c) 2026, Titansoft Limited and contributors
# See license.txt
"""Resolve Funding Request status from the active ERPNext Workflow.

State *labels* live in Desk (Workflow / Workflow State). Python must not assume
"Pending Approval" vs "Pending". This module reads the live workflow and classifies
states from doc_status and the transition graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import frappe
from frappe.utils import cint

FUNDING_REQUEST_DOCTYPE = "Funding Request"
MATERIAL_REQUEST_DOCTYPE = "Material Request"
FUNDING_REQUEST_WORKFLOW = "CGM Funding Request Approval"
MATERIAL_REQUEST_FUNDING_WORKFLOW = "CGM Material Request Funding"
# Requesters/finance send their own draft into the next step. Approve/Reject stay checker-only.
_SELF_SUBMIT_ACTIONS = frozenset({"Submit", "Submit Request"})


def ensure_funding_workflow_self_submit() -> None:
	"""Let the document owner Submit / Submit Request on funding workflows.

	Frappe hides workflow actions from the owner unless Allow Self Approval is on.
	That blocked requesters from submitting their own Material Request, and finance
	from sending their own Funding Request to the Funding Approver.
	"""
	if not frappe.db.exists("DocType", "Workflow"):
		return
	for workflow_name in (MATERIAL_REQUEST_FUNDING_WORKFLOW, FUNDING_REQUEST_WORKFLOW):
		if not frappe.db.exists("Workflow", workflow_name):
			continue
		doc = frappe.get_doc("Workflow", workflow_name)
		changed = False
		for row in doc.transitions:
			if (row.action or "") not in _SELF_SUBMIT_ACTIONS:
				continue
			if cint(row.allow_self_approval):
				continue
			row.allow_self_approval = 1
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
	frappe.clear_cache()


@dataclass(frozen=True)
class FundingWorkflowMap:
	pending_states: frozenset[str] = field(default_factory=frozenset)
	approve_next_states: frozenset[str] = field(default_factory=frozenset)
	reject_next_states: frozenset[str] = field(default_factory=frozenset)
	cancel_next_states: frozenset[str] = field(default_factory=frozenset)
	complete_from_states: frozenset[str] = field(default_factory=frozenset)
	complete_next_states: frozenset[str] = field(default_factory=frozenset)
	recorded_states: frozenset[str] = field(default_factory=frozenset)
	terminal_states: frozenset[str] = field(default_factory=frozenset)
	partial_state: str | None = None
	disbursement_state: str | None = None
	cancel_state: str | None = None

	def is_pending(self, state: str | None) -> bool:
		return bool(state) and state in self.pending_states

	def is_approve_next(self, state: str | None) -> bool:
		return bool(state) and state in self.approve_next_states

	def is_rejected(self, state: str | None) -> bool:
		return bool(state) and state in self.reject_next_states

	def is_cancelled(self, state: str | None) -> bool:
		return bool(state) and (state in self.cancel_next_states)

	def is_completed(self, state: str | None) -> bool:
		return bool(state) and state in self.complete_next_states

	def is_disbursed(self, state: str | None) -> bool:
		return bool(state) and state in self.complete_from_states

	def is_partial(self, state: str | None) -> bool:
		return bool(state) and bool(self.partial_state) and state == self.partial_state

	def approval_is_recorded(self, state: str | None) -> bool:
		return bool(state) and state in self.recorded_states

	def is_terminal(self, state: str | None) -> bool:
		return bool(state) and state in self.terminal_states

	def is_approval_stamp_state(self, state: str | None) -> bool:
		return self.is_approve_next(state) or self.is_partial(state)

	def progress_states(self) -> frozenset[str]:
		states = set(self.approve_next_states) | set(self.complete_from_states)
		if self.partial_state:
			states.add(self.partial_state)
		if self.disbursement_state:
			states.add(self.disbursement_state)
		return frozenset(states)

	@classmethod
	def from_workflow(cls, workflow) -> FundingWorkflowMap:
		if not workflow:
			return cls()
		doc_status = {}
		submitted_in_order = []
		cancelled = set()
		for row in workflow.get("states") or []:
			state = row.get("state")
			if not state:
				continue
			status = cint(row.get("doc_status"))
			doc_status[state] = status
			if status == 1:
				submitted_in_order.append(state)
			elif status == 2:
				cancelled.add(state)

		pending = set()
		approve_next = set()
		cancel_next = set()
		complete_from = set()
		complete_next = set()
		for transition in workflow.get("transitions") or []:
			source = transition.get("state")
			target = transition.get("next_state")
			if not source or not target:
				continue
			from_ds = doc_status.get(source)
			to_ds = doc_status.get(target)
			if to_ds == 2:
				cancel_next.add(target)
			elif from_ds == 0 and to_ds == 1:
				pending.add(source)
				approve_next.add(target)
			elif from_ds == 1 and to_ds == 1 and source != target:
				complete_from.add(source)
				complete_next.add(target)

		reject_next = set()
		for transition in workflow.get("transitions") or []:
			source = transition.get("state")
			target = transition.get("next_state")
			if source not in pending or not target:
				continue
			if doc_status.get(source) == 0 and doc_status.get(target) == 0:
				reject_next.add(target)

		classified = approve_next | complete_from | complete_next
		leftover = [state for state in submitted_in_order if state not in classified]
		partial = leftover[0] if leftover else None
		disbursement = leftover[1] if len(leftover) > 1 else None
		terminal = frozenset(reject_next | cancel_next | complete_next | cancelled)
		cancel_state = next(iter(cancel_next), next(iter(cancelled), None))
		return cls(
			pending_states=frozenset(pending),
			approve_next_states=frozenset(approve_next),
			reject_next_states=frozenset(reject_next),
			cancel_next_states=frozenset(cancel_next),
			complete_from_states=frozenset(complete_from),
			complete_next_states=frozenset(complete_next),
			recorded_states=frozenset(submitted_in_order),
			terminal_states=terminal,
			partial_state=partial,
			disbursement_state=disbursement,
			cancel_state=cancel_state,
		)


def load_doctype_workflow(doctype: str):
	from frappe.model.workflow import get_workflow_name

	name = get_workflow_name(doctype)
	if not name or not isinstance(name, str):
		return None
	return frappe.get_cached_doc("Workflow", name)


def load_funding_request_workflow():
	return load_doctype_workflow(FUNDING_REQUEST_DOCTYPE)


def workflow_state_names(workflow) -> frozenset[str]:
	if not workflow:
		return frozenset()
	return frozenset(
		row.get("state") for row in (workflow.get("states") or []) if row.get("state")
	)


def get_material_request_state_names(mr_workflow=None) -> frozenset[str]:
	if isinstance(mr_workflow, (set, frozenset, list, tuple)):
		return frozenset(mr_workflow)
	if mr_workflow is None:
		mr_workflow = load_doctype_workflow(MATERIAL_REQUEST_DOCTYPE)
	return workflow_state_names(mr_workflow)


def pick_workflow_state(available: frozenset[str], *candidates: str | None, default: str = "") -> str:
	"""Return the first candidate that exists on the live workflow."""
	for name in candidates:
		if name and (not available or name in available):
			return name
	for name in candidates:
		if name:
			return name
	return default


def get_funding_workflow_map(workflow=None) -> FundingWorkflowMap:
	if workflow is None:
		workflow = load_funding_request_workflow()
	return FundingWorkflowMap.from_workflow(workflow)
