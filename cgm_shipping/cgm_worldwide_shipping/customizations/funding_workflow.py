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
# The workflow action that pays a request. Named here because the state map
# below has to recognise it.
DISBURSE_ACTION = "Disburse"


def _named_state(states, *needles: str) -> str | None:
	for state in states:
		low = (state or "").strip().lower()
		if any(needle in low for needle in needles):
			return state
	return None


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
				# Disburse also runs between two submitted states, but it is the
				# payment, not the closing step. Counting it here made Approved a
				# state to complete from and Disbursed read as fully complete, which
				# then refused the very payment the action exists to make.
				if (transition.get("action") or "") == DISBURSE_ACTION:
					continue
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


def funding_approver_role(workflow=None) -> str:
	"""The role the live workflow lets approve a Funding Request.

	Read from the workflow rather than hardcoded, because the states and the roles
	on them are site configuration: a site that renames the role, or routes
	approval through a different one, should still get a message naming the role it
	actually uses.
	"""
	if workflow is None:
		workflow = load_funding_request_workflow()
	if not workflow:
		return ""
	approve_states = _approve_next_states(workflow)
	for row in workflow.get("transitions") or []:
		# Rows come back as Documents, not dicts, so read them with .get().
		allowed = row.get("allowed")
		if row.get("next_state") in approve_states and allowed:
			return allowed
	return ""


def _approve_next_states(workflow) -> frozenset[str]:
	"""States an Approve action leads to."""
	return frozenset(
		row.get("next_state")
		for row in (workflow.get("transitions") or [])
		if (row.get("action") or "").strip().lower() == "approve" and row.get("next_state")
	)


def another_approver_exists(role: str, exclude: str | None = None) -> bool:
	"""Is there anybody besides `exclude` who can approve?

	Deliberately a yes/no and not a list. Naming people in a refusal message
	publishes who holds a finance role to whoever happens to trigger it, and the
	list goes stale the moment somebody joins or leaves. The role is the useful
	part; who currently holds it is a question for the role list.

	Administrator is not counted: nobody chases Administrator to approve a payment.
	"""
	if not role:
		return False
	holders = frappe.get_all(
		"Has Role",
		filters={"role": role, "parenttype": "User"},
		pluck="parent",
	)
	for user in set(holders):
		if user == exclude or user == "Administrator":
			continue
		if frappe.db.get_value("User", user, "enabled"):
			return True
	return False


def ensure_funding_disburse_transition() -> bool:
	"""Add the Disburse action to the Funding Request workflow where it is missing.

	The workflow is built and owned in Desk, so this adds and never edits: a
	state that already has a Disburse transition is left exactly as it is, and
	no other transition is touched. Runs on every migrate.

	Disburse is offered from each state where money can still go out - approved,
	partially approved, and disbursement in progress - and leads to the workflow's
	Disbursed state. It is allowed to whoever may already act on the request in
	that state, taken from the transitions that state has.
	"""
	cached = load_funding_request_workflow()
	if not cached:
		return False
	# A fresh copy: the cached one is shared and must not be edited in place.
	workflow = frappe.get_doc("Workflow", cached.name)
	wf = get_funding_workflow_map(workflow)
	disbursed = next(iter(wf.disbursed_states()), None)
	if not disbursed:
		return False
	sources = [s for s in (*sorted(wf.approve_next_states), wf.partial_state, wf.disbursement_state) if s]
	sources = [s for s in dict.fromkeys(sources) if s != disbursed]

	changed = False
	for state in sources:
		existing = [t for t in workflow.transitions if t.state == state]
		if any((t.action or "") == DISBURSE_ACTION for t in existing):
			continue
		allowed = next((t.allowed for t in existing if t.allowed), None) or next(
			(s.allow_edit for s in workflow.states if s.state == state and s.allow_edit), None
		)
		if not allowed:
			continue
		workflow.append(
			"transitions",
			{
				"state": state,
				"action": DISBURSE_ACTION,
				"next_state": disbursed,
				"allowed": allowed,
				"allow_self_approval": 1,
			},
		)
		changed = True
	if changed:
		_ensure_workflow_action_masters((DISBURSE_ACTION,))
		workflow.flags.ignore_permissions = True
		workflow.save()
		frappe.clear_cache(doctype=FUNDING_REQUEST_DOCTYPE)
	return changed

