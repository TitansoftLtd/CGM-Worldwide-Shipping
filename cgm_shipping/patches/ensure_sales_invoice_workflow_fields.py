"""Custom fields for Sales Invoice finance approval workflow."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _upsert_cf

MODULE = "CGM Worldwide Shipping"


def execute() -> None:
	_ensure_sales_invoice_workflow_fields()
	frappe.db.commit()


def _ensure_sales_invoice_workflow_fields() -> None:
	_upsert_cf(
		"Sales Invoice",
		{
			"fieldname": "workflow_state",
			"label": "Workflow State",
			"fieldtype": "Link",
			"options": "Workflow State",
			"insert_after": "naming_series",
			"hidden": 1,
			"no_copy": 1,
			"allow_on_submit": 1,
			"read_only": 1,
		},
	)
	_upsert_cf(
		"Sales Invoice",
		{
			"fieldname": "custom_finance_approved_by",
			"label": "Finance Approved By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "workflow_state",
			"read_only": 1,
			"allow_on_submit": 1,
		},
	)
	_upsert_cf(
		"Sales Invoice",
		{
			"fieldname": "custom_finance_rejected_by",
			"label": "Finance Rejected By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "custom_finance_approved_by",
			"read_only": 1,
		},
	)
	_upsert_cf(
		"Sales Invoice",
		{
			"fieldname": "custom_finance_rejection_reason",
			"label": "Finance Rejection Reason",
			"fieldtype": "Small Text",
			"insert_after": "custom_finance_rejected_by",
			"depends_on": "eval:doc.workflow_state=='Rejected'",
		},
	)
