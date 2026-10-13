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

# What a Funding Request is waiting on, and so what its action is called. The
# menu used to say "Disburse" whatever was pending - including on a request whose
# Purchase Order was already raised, where there was nothing left to disburse and
# the real next step was on the order. Each of these is both the value of
# `Funding Request.pending_step` and the workflow action offered for it.
STEP_DISBURSE = DISBURSE_ACTION  # a row still needs its payment document
STEP_CREATE_PURCHASE_ORDER = "Create Purchase Order"  # only Purchase rows need one
STEP_SUBMIT_JOURNAL_ENTRY = "Submit Journal Entry"  # a draft entry is waiting to be posted
STEP_SUBMIT_PURCHASE_ORDER = "Submit Purchase Order"  # the order is still a draft
STEP_RECORD_PURCHASE_PAYMENT = "Record Purchase Payment"  # the order is placed, not yet paid

# These create or post documents, and move the request on.
PAYING_STEPS = (STEP_DISBURSE, STEP_CREATE_PURCHASE_ORDER, STEP_SUBMIT_JOURNAL_ENTRY)
# These are done on the Purchase Order itself; the action takes the user there.
PURCHASE_ORDER_STEPS = (STEP_SUBMIT_PURCHASE_ORDER, STEP_RECORD_PURCHASE_PAYMENT)
PENDING_STEPS = PAYING_STEPS + PURCHASE_ORDER_STEPS
# What the action that cancels a Funding Request is called. Plain "Cancel" in a
# menu reads as "close this menu".
CANCEL_ACTION = "Cancel Request"


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
	# Where the paying actions lead. Named outright so that "which state means
	# paid" does not depend on a Complete step existing after it.
	disbursed_state: str | None = None
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
		if self.disbursed_state:
			return frozenset({self.disbursed_state})
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
		# Disbursed is a payment-driven state like the others: cancelling the entry
		# that paid a request has to be able to take it back out of Disbursed.
		states |= self.disbursed_states()
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
		paid_targets = []
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
				if (transition.get("action") or "") in PENDING_STEPS:
					if (transition.get("action") or "") in PAYING_STEPS and target not in paid_targets:
						paid_targets.append(target)
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
		leftover = [
			state
			for state in submitted_in_order
			if state not in classified and (state or "").strip().lower() != "disbursed"
		]
		partial = _named_state(submitted_in_order, "partial") or (leftover[0] if leftover else None)
		named_disbursement = _named_state(submitted_in_order, "disbursement in progress")
		rest = [state for state in leftover if state != partial]
		disbursement = named_disbursement or (rest[0] if rest else None)
		# Rejected / Cancelled return Material Requests to the pool.
		# Disbursed / Completed stay linked so the request is not funded twice.
		# The paid state: where the paying actions lead, else the submitted state
		# called Disbursed. Left empty on a workflow that has neither, so the older
		# reading of it from the Complete step still applies there.
		disbursed_state = (paid_targets[0] if paid_targets else None) or next(
			(state for state in submitted_in_order if (state or "").strip().lower() == "disbursed"), None
		)
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
			disbursed_state=disbursed_state,
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
	"""Add the payment actions to the Funding Request workflow where they are missing.

	The workflow is built and owned in Desk, so this adds and never edits: an
	action a state already has is left exactly as it is, apart from being given
	its condition when it has none. No other transition is touched. Runs on every
	migrate.

	Every state where money can still go out - approved, partially approved, and
	disbursement in progress - gets one action per pending step, each shown only
	while `pending_step` names it. So the menu offers exactly one of them, and it
	reads as what is actually waiting to be done:

	* Disburse, Create Purchase Order, Submit Journal Entry lead to the Disbursed
	  state and are what create or post the documents.
	* Submit Purchase Order and Record Purchase Payment stay in the same state.
	  That work is done on the order, and the form takes the user there.

	Allowed to whoever may already act on the request in that state.
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
		allowed = next((t.allowed for t in existing if t.allowed), None) or next(
			(s.allow_edit for s in workflow.states if s.state == state and s.allow_edit), None
		)
		if not allowed:
			continue
		for step in PENDING_STEPS:
			condition = f'doc.pending_step == "{step}"'
			current = next((t for t in existing if (t.action or "") == step), None)
			if current is not None:
				if not (current.get("condition") or "").strip():
					current.condition = condition
					changed = True
				continue
			workflow.append(
				"transitions",
				{
					"state": state,
					"action": step,
					"next_state": disbursed if step in PAYING_STEPS else state,
					"allowed": allowed,
					"allow_self_approval": 1,
					"condition": condition,
				},
			)
			changed = True
	if changed:
		_ensure_workflow_action_masters(PENDING_STEPS)
		_put_disburse_first(workflow)
		workflow.flags.ignore_permissions = True
		workflow.save()
		frappe.clear_cache(doctype=FUNDING_REQUEST_DOCTYPE)
	return changed


def ensure_material_request_progress_state() -> bool:
	"""Give the Material Request workflow the Funding Request's in-progress state.

	A Material Request mirrors its Funding Request: on a request, approved,
	disbursed. It had nothing between Approved and Disbursed, so a requester saw
	"Approved" from the moment of approval until the last shilling was paid, with
	no sign that their entry or order had been raised. The code already writes the
	Funding Request's state onto the Material Request whenever the Material Request
	workflow has a state of that name; this adds the one that was missing.

	Add-only. No transition is added: the state is set by the Funding Request, not
	by anyone acting on the Material Request.
	"""
	cached = load_doctype_workflow(MATERIAL_REQUEST_DOCTYPE)
	in_progress = get_funding_workflow_map().disbursement_state
	if not cached or not in_progress:
		return False
	workflow = frappe.get_doc("Workflow", cached.name)
	if any(row.state == in_progress for row in workflow.states):
		return False
	approved = next((row for row in workflow.states if (row.state or "").strip().lower() == "approved"), None)
	if not approved:
		return False
	if not frappe.db.exists("Workflow State", in_progress):
		frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": in_progress}).insert(
			ignore_permissions=True
		)
	workflow.append(
		"states",
		{"state": in_progress, "doc_status": approved.doc_status, "allow_edit": approved.allow_edit},
	)
	workflow.flags.ignore_permissions = True
	workflow.save()
	frappe.clear_cache(doctype=MATERIAL_REQUEST_DOCTYPE)
	return True


def ensure_funding_completed_cancel_transition() -> bool:
	"""Let a paid Funding Request be cancelled, where it cannot be yet.

	The last state was a dead end: no action led out of it, so a request closed by
	mistake could not be undone from the form. This gives Disbursed (and Completed,
	on a workflow that still has it) the same cancelling action the earlier states
	have. Add-only.

	Cancelling takes the request's entries and orders with it; see
	`funding.cancel_funding_payment_documents`.
	"""
	cached = load_funding_request_workflow()
	if not cached:
		return False
	workflow = frappe.get_doc("Workflow", cached.name)
	wf = get_funding_workflow_map(workflow)
	if not wf.cancel_state:
		return False
	changed = False
	for state_row in workflow.states:
		state = state_row.state
		if not (wf.is_fully_complete(state) or wf.is_disbursed(state)):
			continue
		if any(t.state == state and t.next_state == wf.cancel_state for t in workflow.transitions):
			continue
		if not state_row.allow_edit:
			continue
		workflow.append(
			"transitions",
			{
				"state": state,
				"action": CANCEL_ACTION,
				"next_state": wf.cancel_state,
				"allowed": state_row.allow_edit,
				"allow_self_approval": 1,
			},
		)
		changed = True
	if changed:
		_ensure_workflow_action_masters((CANCEL_ACTION,))
		workflow.flags.ignore_permissions = True
		workflow.save()
		frappe.clear_cache(doctype=FUNDING_REQUEST_DOCTYPE)
	return changed


def retire_funding_completed_state() -> dict:
	"""Make Disbursed the last state: drop the Complete step and the Completed state.

	Completed recorded only that someone pressed Complete after the money had
	already gone out. Nothing read it: Material Requests were marked Disbursed at
	the Disbursed stage, and no report or notification referred to it.

	Requests already Completed are moved to Disbursed first, so no request is left
	in a state the workflow no longer has. Their amounts, dates and Material
	Requests are untouched; Material Requests already read Disbursed.

	One-time, called from a patch. Unlike the add-only helpers above this removes
	something, so it does not run on every migrate.
	"""
	cached = load_funding_request_workflow()
	if not cached:
		return {"moved": 0, "removed": []}
	workflow = frappe.get_doc("Workflow", cached.name)
	wf = get_funding_workflow_map(workflow)
	disbursed = next(iter(wf.disbursed_states()), None)
	retired = [
		row.state
		for row in workflow.states
		if row.state != disbursed and wf.is_fully_complete(row.state)
	]
	if not disbursed or not retired:
		return {"moved": 0, "removed": []}

	moved = 0
	for name in frappe.get_all(
		FUNDING_REQUEST_DOCTYPE, filters={"workflow_state": ["in", retired]}, pluck="name"
	):
		frappe.db.set_value(FUNDING_REQUEST_DOCTYPE, name, "workflow_state", disbursed, update_modified=False)
		moved += 1

	workflow.set(
		"transitions",
		[t for t in workflow.transitions if t.state not in retired and t.next_state not in retired],
	)
	for position, row in enumerate(workflow.transitions, start=1):
		row.idx = position
	workflow.set("states", [row for row in workflow.states if row.state not in retired])
	for position, row in enumerate(workflow.states, start=1):
		row.idx = position
	workflow.flags.ignore_permissions = True
	workflow.save()
	frappe.clear_cache(doctype=FUNDING_REQUEST_DOCTYPE)
	return {"moved": moved, "removed": retired}


def _put_disburse_first(workflow) -> bool:
	"""Order each state's actions so the payment step is listed before the others.

	The Actions menu lists a state's transitions in table order. The pending
	payment step is what Finance is there to do; cancelling is the exception, and
	it sat above it. Only the payment actions move, and only within their own
	state's rows.
	"""
	rows = list(workflow.transitions)
	ordered = []
	placed = set()
	for row in rows:
		if id(row) in placed:
			continue
		if (row.action or "") not in PENDING_STEPS:
			for step in PENDING_STEPS:
				for r in rows:
					if id(r) not in placed and r.state == row.state and (r.action or "") == step:
						ordered.append(r)
						placed.add(id(r))
		ordered.append(row)
		placed.add(id(row))
	if [id(r) for r in ordered] == [id(r) for r in rows]:
		return False
	workflow.set("transitions", ordered)
	# Rows keep their old position number when re-set; the table is saved and
	# read back in that order, so it has to be rewritten.
	for position, row in enumerate(workflow.transitions, start=1):
		row.idx = position
	return True


def tidy_funding_request_actions() -> dict:
	"""Rename the cancelling action and list Disburse first. Safe to run again."""
	cached = load_funding_request_workflow()
	if not cached:
		return {"renamed": 0, "reordered": False}
	workflow = frappe.get_doc("Workflow", cached.name)
	cancelled = {s.state for s in workflow.states if cint(s.doc_status) == 2}
	renamed = 0
	for row in workflow.transitions:
		if row.next_state in cancelled and (row.action or "") == "Cancel":
			row.action = CANCEL_ACTION
			renamed += 1
	reordered = _put_disburse_first(workflow)
	if renamed or reordered:
		_ensure_workflow_action_masters((CANCEL_ACTION,))
		workflow.flags.ignore_permissions = True
		workflow.save()
		frappe.clear_cache(doctype=FUNDING_REQUEST_DOCTYPE)
	return {"renamed": renamed, "reordered": reordered}

