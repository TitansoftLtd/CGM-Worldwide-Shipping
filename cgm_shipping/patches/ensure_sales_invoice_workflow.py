"""Install CGM Sales Invoice finance approval workflow (idempotent)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SALES_INVOICE_WORKFLOW_NAME,
	SALES_INVOICE_WORKFLOW_STATE_APPROVED,
	SALES_INVOICE_WORKFLOW_STATE_DRAFT,
	SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
	SALES_INVOICE_WORKFLOW_STATE_REJECTED,
)

WORKFLOW_ACTIONS = (
	"Submit for Finance Approval",
	"Approve",
	"Reject",
	"Return to Draft",
)


def execute() -> None:
	if not frappe.db.exists("DocType", "Workflow"):
		return

	_ensure_workflow_action_masters()
	_sync_workflow()
	_backfill_existing_sales_invoices()
	frappe.db.commit()


def _sync_workflow() -> None:
	_ensure_workflow_states()

	if frappe.db.exists("Workflow", SALES_INVOICE_WORKFLOW_NAME):
		workflow = frappe.get_doc("Workflow", SALES_INVOICE_WORKFLOW_NAME)
	else:
		workflow = frappe.new_doc("Workflow")
		workflow.workflow_name = SALES_INVOICE_WORKFLOW_NAME

	workflow.document_type = "Sales Invoice"
	workflow.workflow_state_field = "workflow_state"
	workflow.is_active = 1
	workflow.send_email_alert = 0
	workflow.override_status = 0

	workflow.states = []
	for row in _workflow_states():
		workflow.append("states", row)

	workflow.transitions = []
	for row in _workflow_transitions():
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
			"state": SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
			"doc_status": "0",
			"allow_edit": "Accounts Manager",
			"is_optional_state": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_APPROVED,
			"doc_status": "0",
			"allow_edit": "Accounts User",
			"is_optional_state": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_REJECTED,
			"doc_status": "0",
			"allow_edit": "Accounts User",
			"is_optional_state": 0,
		},
	]


def _workflow_transitions() -> list[dict]:
	return [
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_DRAFT,
			"action": "Submit for Finance Approval",
			"next_state": SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
			"allowed": "Accounts User",
			"allow_self_approval": 1,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_DRAFT,
			"action": "Submit for Finance Approval",
			"next_state": SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
			"allowed": "Accounts Manager",
			"allow_self_approval": 1,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
			"action": "Approve",
			"next_state": SALES_INVOICE_WORKFLOW_STATE_APPROVED,
			"allowed": "Accounts Manager",
			"allow_self_approval": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
			"action": "Approve",
			"next_state": SALES_INVOICE_WORKFLOW_STATE_APPROVED,
			"allowed": "Accounts User",
			"allow_self_approval": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
			"action": "Reject",
			"next_state": SALES_INVOICE_WORKFLOW_STATE_REJECTED,
			"allowed": "Accounts Manager",
			"allow_self_approval": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
			"action": "Reject",
			"next_state": SALES_INVOICE_WORKFLOW_STATE_REJECTED,
			"allowed": "Accounts User",
			"allow_self_approval": 0,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_REJECTED,
			"action": "Return to Draft",
			"next_state": SALES_INVOICE_WORKFLOW_STATE_DRAFT,
			"allowed": "Accounts User",
			"allow_self_approval": 1,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_REJECTED,
			"action": "Return to Draft",
			"next_state": SALES_INVOICE_WORKFLOW_STATE_DRAFT,
			"allowed": "Accounts Manager",
			"allow_self_approval": 1,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_REJECTED,
			"action": "Submit for Finance Approval",
			"next_state": SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
			"allowed": "Accounts User",
			"allow_self_approval": 1,
		},
		{
			"state": SALES_INVOICE_WORKFLOW_STATE_REJECTED,
			"action": "Submit for Finance Approval",
			"next_state": SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
			"allowed": "Accounts Manager",
			"allow_self_approval": 1,
		},
	]


def _ensure_workflow_states() -> None:
	for state_name in (
		SALES_INVOICE_WORKFLOW_STATE_DRAFT,
		SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE,
		SALES_INVOICE_WORKFLOW_STATE_APPROVED,
		SALES_INVOICE_WORKFLOW_STATE_REJECTED,
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


def _backfill_existing_sales_invoices() -> None:
	if not frappe.db.has_column("Sales Invoice", "workflow_state"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabSales Invoice`
		SET workflow_state = %s
		WHERE docstatus = 1
			AND (workflow_state IS NULL OR workflow_state = '')
		""",
		SALES_INVOICE_WORKFLOW_STATE_APPROVED,
	)
	frappe.db.sql(
		"""
		UPDATE `tabSales Invoice`
		SET workflow_state = %s
		WHERE docstatus = 0
			AND (workflow_state IS NULL OR workflow_state = '')
		""",
		SALES_INVOICE_WORKFLOW_STATE_DRAFT,
	)
