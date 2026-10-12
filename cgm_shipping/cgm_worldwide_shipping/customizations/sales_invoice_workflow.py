"""CGM Sales Invoice approval workflow, kept in step with the code on every migrate.

Maker-checker gate only: Draft → Pending Approval → Approved (submitted).
Rejection returns to Draft. Cancellation uses Approved → Cancelled.

ERPNext owns payment Status (Unpaid / Partly Paid / Paid / Overdue) via
override_status on the Workflow - workflow_state is approval-only.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SALES_INVOICE_WORKFLOW_ACTION_APPROVE,
	SALES_INVOICE_WORKFLOW_ACTION_CANCEL,
	SALES_INVOICE_WORKFLOW_ACTION_REJECT,
	SALES_INVOICE_WORKFLOW_ACTION_SUBMIT_FOR_REVIEW,
	SALES_INVOICE_WORKFLOW_NAME,
	SALES_INVOICE_WORKFLOW_STATE_APPROVED,
	SALES_INVOICE_WORKFLOW_STATE_CANCELLED,
	SALES_INVOICE_WORKFLOW_STATE_DRAFT,
	SALES_INVOICE_WORKFLOW_STATE_PENDING,
)

WORKFLOW_ACTIONS = (
	SALES_INVOICE_WORKFLOW_ACTION_SUBMIT_FOR_REVIEW,
	SALES_INVOICE_WORKFLOW_ACTION_APPROVE,
	SALES_INVOICE_WORKFLOW_ACTION_REJECT,
	SALES_INVOICE_WORKFLOW_ACTION_CANCEL,
)


def ensure_sales_invoice_workflow() -> None:
	"""Add any Sales Invoice workflow states/transitions the code needs; keep desk edits."""
	if not frappe.db.exists("DocType", "Workflow"):
		return
	_ensure_workflow_action_masters()
	_sync_workflow()


def _sync_workflow() -> None:
	"""Create the workflow, or add the states and transitions the code needs.

	Runs on every migrate (install.after_migrate). Rows already on the workflow are
	left alone, so a role or edit rule changed in the desk survives; changing an
	existing row from code needs a patch.
	"""
	_ensure_workflow_states()

	if not frappe.db.exists("Workflow", SALES_INVOICE_WORKFLOW_NAME):
		workflow = frappe.new_doc("Workflow")
		workflow.workflow_name = SALES_INVOICE_WORKFLOW_NAME
		workflow.document_type = "Sales Invoice"
		workflow.workflow_state_field = "workflow_state"
		workflow.is_active = 1
		workflow.send_email_alert = 0
		# Don't Override Status - list/form indicators use ERPNext payment status.
		workflow.override_status = 1
		for row in _workflow_states():
			workflow.append("states", row)
		for row in _workflow_transitions():
			workflow.append("transitions", row)
		workflow.insert(ignore_permissions=True)
		return

	workflow = frappe.get_doc("Workflow", SALES_INVOICE_WORKFLOW_NAME)
	have_states = {row.state for row in workflow.states}
	have_transitions = {(row.state, row.action) for row in workflow.transitions}
	missing_states = [row for row in _workflow_states() if row["state"] not in have_states]
	missing_transitions = [
		row for row in _workflow_transitions() if (row["state"], row["action"]) not in have_transitions
	]
	if not (missing_states or missing_transitions):
		return
	for row in missing_states:
		workflow.append("states", row)
	for row in missing_transitions:
		workflow.append("transitions", row)
	workflow.save(ignore_permissions=True)


def _workflow_states() -> list[dict]:
	return [
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_DRAFT,
			"doc_status": "0",
			"allow_edit": "Accounts User",
			"is_optional_state": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_PENDING,
			"doc_status": "0",
			# Lock maker edits while awaiting manager review.
			"allow_edit": "Accounts Manager",
			"is_optional_state": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_APPROVED,
			"doc_status": "1",
			# Allow allow-on-submit fields (e.g. Share with Customer) after submit.
			"allow_edit": "Accounts User",
			"is_optional_state": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_CANCELLED,
			"doc_status": "2",
			"allow_edit": "Accounts Manager",
			"is_optional_state": 0,
		},
	]


def _workflow_transitions() -> list[dict]:
	return [
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_DRAFT,
			"action": SALES_INVOICE_WORKFLOW_ACTION_SUBMIT_FOR_REVIEW,
			"next_state": SALES_INVOICE_WORKFLOW_STATE_PENDING,
			"allowed": "Accounts User",
			"allow_self_approval": 1,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_PENDING,
			"action": SALES_INVOICE_WORKFLOW_ACTION_APPROVE,
			"next_state": SALES_INVOICE_WORKFLOW_STATE_APPROVED,
			"allowed": "Accounts Manager",
			"allow_self_approval": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_PENDING,
			"action": SALES_INVOICE_WORKFLOW_ACTION_REJECT,
			"next_state": SALES_INVOICE_WORKFLOW_STATE_DRAFT,
			"allowed": "Accounts Manager",
			"allow_self_approval": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_APPROVED,
			"action": SALES_INVOICE_WORKFLOW_ACTION_CANCEL,
			"next_state": SALES_INVOICE_WORKFLOW_STATE_CANCELLED,
			"allowed": "Accounts Manager",
			"allow_self_approval": 0,
		},
	]


def _ensure_workflow_states() -> None:
	for state_name in (
		SALES_INVOICE_WORKFLOW_STATE_DRAFT,
		SALES_INVOICE_WORKFLOW_STATE_PENDING,
		SALES_INVOICE_WORKFLOW_STATE_APPROVED,
		SALES_INVOICE_WORKFLOW_STATE_CANCELLED,
	):
		if frappe.db.exists("Workflow State", state_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Workflow State",
				"workflow_state_name": state_name,
				"style": "Primary",
			}
		).insert(ignore_permissions=True)


def _ensure_workflow_action_masters() -> None:
	for action_name in WORKFLOW_ACTIONS:
		if frappe.db.exists("Workflow Action Master", action_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Workflow Action Master",
				"workflow_action_name": action_name,
			}
		).insert(ignore_permissions=True)
