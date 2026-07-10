"""Install CGM Quotation approval workflow (idempotent)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	QUOTATION_WORKFLOW_NAME,
	QUOTATION_WORKFLOW_STATE_APPROVED,
	QUOTATION_WORKFLOW_STATE_DRAFT,
	QUOTATION_WORKFLOW_STATE_PENDING_FINANCE,
	QUOTATION_WORKFLOW_STATE_REJECTED,
	QUOTATION_WORKFLOW_STATE_SHARED,
)


WORKFLOW_ACTIONS = (
	"Submit for Finance Approval",
	"Approve",
	"Reject",
	"Share with Client",
)


def execute() -> None:
	if not frappe.db.exists("DocType", "Workflow"):
		return

	_ensure_workflow_action_masters()
	_ensure_workflow()
	_backfill_existing_quotations()
	frappe.db.commit()


def _ensure_workflow() -> None:
	_ensure_workflow_states()

	if frappe.db.exists("Workflow", QUOTATION_WORKFLOW_NAME):
		workflow = frappe.get_doc("Workflow", QUOTATION_WORKFLOW_NAME)
		workflow.is_active = 1
		workflow.save(ignore_permissions=True)
		return

	workflow = frappe.new_doc("Workflow")
	workflow.workflow_name = QUOTATION_WORKFLOW_NAME
	workflow.document_type = "Quotation"
	workflow.workflow_state_field = "workflow_state"
	workflow.is_active = 1
	workflow.send_email_alert = 0
	workflow.override_status = 0

	states = [
		{
			"state": QUOTATION_WORKFLOW_STATE_DRAFT,
			"doc_status": "0",
			"allow_edit": "Sales User",
			"is_optional_state": 0,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_PENDING_FINANCE,
			"doc_status": "1",
			"allow_edit": "Accounts Manager",
			"is_optional_state": 0,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_APPROVED,
			"doc_status": "1",
			"allow_edit": "Sales Manager",
			"is_optional_state": 0,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_REJECTED,
			"doc_status": "1",
			"allow_edit": "Sales User",
			"is_optional_state": 0,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_SHARED,
			"doc_status": "1",
			"allow_edit": "Sales User",
			"is_optional_state": 0,
		},
	]
	for row in states:
		workflow.append("states", row)

	transitions = [
		{
			"state": QUOTATION_WORKFLOW_STATE_DRAFT,
			"action": "Submit for Finance Approval",
			"next_state": QUOTATION_WORKFLOW_STATE_PENDING_FINANCE,
			"allowed": "Sales User",
			"allow_self_approval": 1,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_DRAFT,
			"action": "Submit for Finance Approval",
			"next_state": QUOTATION_WORKFLOW_STATE_PENDING_FINANCE,
			"allowed": "Sales Manager",
			"allow_self_approval": 1,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_PENDING_FINANCE,
			"action": "Approve",
			"next_state": QUOTATION_WORKFLOW_STATE_APPROVED,
			"allowed": "Accounts Manager",
			"allow_self_approval": 0,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_PENDING_FINANCE,
			"action": "Approve",
			"next_state": QUOTATION_WORKFLOW_STATE_APPROVED,
			"allowed": "Accounts User",
			"allow_self_approval": 0,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_PENDING_FINANCE,
			"action": "Reject",
			"next_state": QUOTATION_WORKFLOW_STATE_REJECTED,
			"allowed": "Accounts Manager",
			"allow_self_approval": 0,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_PENDING_FINANCE,
			"action": "Reject",
			"next_state": QUOTATION_WORKFLOW_STATE_REJECTED,
			"allowed": "Accounts User",
			"allow_self_approval": 0,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_APPROVED,
			"action": "Share with Client",
			"next_state": QUOTATION_WORKFLOW_STATE_SHARED,
			"allowed": "Sales User",
			"allow_self_approval": 1,
		},
		{
			"state": QUOTATION_WORKFLOW_STATE_APPROVED,
			"action": "Share with Client",
			"next_state": QUOTATION_WORKFLOW_STATE_SHARED,
			"allowed": "Sales Manager",
			"allow_self_approval": 1,
		},
	]
	for row in transitions:
		workflow.append("transitions", row)

	workflow.insert(ignore_permissions=True)


def _ensure_workflow_states() -> None:
	for state_name in (
		QUOTATION_WORKFLOW_STATE_DRAFT,
		QUOTATION_WORKFLOW_STATE_PENDING_FINANCE,
		QUOTATION_WORKFLOW_STATE_APPROVED,
		QUOTATION_WORKFLOW_STATE_REJECTED,
		QUOTATION_WORKFLOW_STATE_SHARED,
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


def _backfill_existing_quotations() -> None:
	"""Submitted quotations created before workflow existed default to Approved."""
	if not frappe.db.has_column("Quotation", "workflow_state"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabQuotation`
		SET workflow_state = %s
		WHERE docstatus = 1
			AND (workflow_state IS NULL OR workflow_state = '')
		""",
		QUOTATION_WORKFLOW_STATE_APPROVED,
	)
