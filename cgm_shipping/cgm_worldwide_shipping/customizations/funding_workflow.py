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

_PURCHASE_CONDITION = 'doc.material_request_type != "Operational Expense"'
_OPERATIONAL_CONDITION = 'doc.material_request_type == "Operational Expense"'


def _named_state(states, *needles: str) -> str | None:
	for state in states:
		low = (state or "").strip().lower()
		if any(needle in low for needle in needles):
			return state
	return None


def simplify_funding_workflow_records() -> dict:
	"""Replace role-copied transitions with one transition per business step.

	ERPNext permissions decide who can open the document. The workflow only
	encodes the state machine. This writes the live Workflow records.
	"""
	if not frappe.db.exists("DocType", "Workflow"):
		return {"material_request": 0, "funding_request": 0}

	_ensure_roles(("All", "Finance User", "Funding Approver"))
	_ensure_workflow_action_masters(
		(
			"Submit",
			"Resubmit",
			"Cancel",
			"Approve",
			"Reject",
			"Complete",
		)
	)

	mr_count = _replace_workflow_transitions(
		MATERIAL_REQUEST_FUNDING_WORKFLOW,
		_material_request_transitions(),
		state_edits=_material_request_state_edits(),
	)
	fr_count = _replace_workflow_transitions(
		FUNDING_REQUEST_WORKFLOW,
		_funding_request_transitions(),
		state_edits=_funding_request_state_edits(),
	)
	frappe.clear_cache()
	return {"material_request": mr_count, "funding_request": fr_count}


def _material_request_transitions() -> list[dict]:
	return [
		_transition("Draft", "Submit", "Submitted", "All", 1, _PURCHASE_CONDITION),
		_transition("Draft", "Submit", "Unfunded", "All", 1, _OPERATIONAL_CONDITION),
		_transition("Submitted", "Cancel", "Cancelled", "All", 1, _PURCHASE_CONDITION),
		_transition("Unfunded", "Cancel", "Cancelled", "All", 1, _OPERATIONAL_CONDITION),
		_transition("Rejected", "Cancel", "Cancelled", "All", 1),
	]


def _funding_request_transitions() -> list[dict]:
	return [
		_transition("Draft", "Submit", "Pending", "Finance User", 1),
		_transition("Rejected", "Resubmit", "Pending", "Finance User", 1),
		_transition("Pending", "Approve", "Approved", "Funding Approver", 1),
		_transition("Pending", "Reject", "Rejected", "Funding Approver", 1),
		_transition("Approved", "Cancel", "Cancelled", "Finance User", 1),
		_transition("Partially Approved", "Cancel", "Cancelled", "Finance User", 1),
		_transition("Disbursement in Progress", "Cancel", "Cancelled", "Finance User", 1),
		_transition("Disbursed", "Complete", "Completed", "Finance User", 1),
	]


def _material_request_state_edits() -> dict[str, dict]:
	return {
		"Draft": {"allow_edit": "All", "send_email": 0},
		"Submitted": {"allow_edit": "All", "send_email": 0},
		"Unfunded": {"allow_edit": "All", "send_email": 0},
		"On Funding Request": {"allow_edit": "All", "send_email": 0},
		"Pending": {"allow_edit": "All", "send_email": 0},
		"Approved": {"allow_edit": "All", "send_email": 0},
		"Partially Approved": {"allow_edit": "All", "send_email": 0},
		"Disbursed": {"allow_edit": "All", "send_email": 0},
		"Rejected": {"allow_edit": "All", "send_email": 0},
		"Cancelled": {"allow_edit": "All", "send_email": 0},
	}


def _funding_request_state_edits() -> dict[str, dict]:
	return {
		"Draft": {"allow_edit": "Finance User", "send_email": 0},
		"Pending": {"allow_edit": "Funding Approver", "send_email": 0},
		"Approved": {"allow_edit": "Finance User", "send_email": 0},
		"Partially Approved": {"allow_edit": "Finance User", "send_email": 0},
		"Disbursement in Progress": {"allow_edit": "Finance User", "send_email": 0},
		"Disbursed": {"allow_edit": "Finance User", "send_email": 0},
		"Completed": {"allow_edit": "Finance User", "send_email": 0},
		"Rejected": {"allow_edit": "Finance User", "send_email": 0},
		"Cancelled": {"allow_edit": "Finance User", "send_email": 0},
	}


def _transition(state, action, next_state, allowed, allow_self_approval, condition=None) -> dict:
	row = {
		"state": state,
		"action": action,
		"next_state": next_state,
		"allowed": allowed,
		"allow_self_approval": allow_self_approval,
	}
	if condition:
		row["condition"] = condition
	return row


def _replace_workflow_transitions(workflow_name: str, transitions: list[dict], state_edits=None) -> int:
	if not frappe.db.exists("Workflow", workflow_name):
		return 0
	doc = frappe.get_doc("Workflow", workflow_name)
	doc.send_email_alert = 0
	for row in doc.states:
		edits = (state_edits or {}).get(row.state) or {"send_email": 0}
		for field, value in edits.items():
			row.set(field, value)
	doc.transitions = []
	for row in transitions:
		doc.append("transitions", row)
	doc.save(ignore_permissions=True)
	return len(doc.transitions)


def _ensure_roles(names: tuple[str, ...]) -> None:
	for name in names:
		if frappe.db.exists("Role", name):
			continue
		frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 1}).insert(
			ignore_permissions=True
		)


def _ensure_workflow_action_masters(names: tuple[str, ...]) -> None:
	if not frappe.db.exists("DocType", "Workflow Action Master"):
		return
	for name in names:
		if frappe.db.exists("Workflow Action Master", name):
			continue
		frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": name}).insert(
			ignore_permissions=True
		)


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

	def disbursed_states(self) -> frozenset[str]:
		"""States that mean money has gone out, not merely that approval is recorded."""
		extra = set()
		if self.partial_state:
			extra.add(self.partial_state)
		if self.disbursement_state:
			extra.add(self.disbursement_state)
		candidates = self.complete_from_states - self.approve_next_states - extra
		named = frozenset(
			state
			for state in self.complete_from_states | self.complete_next_states
			if (state or "").strip().lower() == "disbursed"
		)
		return named or frozenset(candidates)

	def is_disbursed(self, state: str | None) -> bool:
		return bool(state) and state in self.disbursed_states()

	def is_fully_complete(self, state: str | None) -> bool:
		"""True for the final Completed state, not mid-progress after Approve."""
		if not self.is_completed(state):
			return False
		if self.is_partial(state) or state in self.approve_next_states:
			return False
		if state == self.disbursement_state:
			return False
		if state in self.complete_from_states and state not in self.disbursed_states():
			return False
		return True

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
		partial = _named_state(submitted_in_order, "partial") or (leftover[0] if leftover else None)
		named_disbursement = _named_state(submitted_in_order, "disbursement in progress")
		rest = [state for state in leftover if state != partial]
		disbursement = named_disbursement or (rest[0] if rest else None)
		# Rejected / Cancelled return Material Requests to the pool.
		# Disbursed / Completed stay linked so the request is not funded twice.
		terminal = frozenset(reject_next | cancel_next | cancelled)
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
