"""Custom fields for Sales Invoice approval workflow."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SALES_INVOICE_APPROVED_BY_FIELD,
	SALES_INVOICE_REJECTED_BY_FIELD,
	SALES_INVOICE_REJECTION_REASON_FIELD,
)
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
			"fieldname": SALES_INVOICE_APPROVED_BY_FIELD,
			"label": "Approved By",
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
			"fieldname": SALES_INVOICE_REJECTED_BY_FIELD,
			"label": "Rejected By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": SALES_INVOICE_APPROVED_BY_FIELD,
			"read_only": 1,
			"depends_on": f"eval:doc.{SALES_INVOICE_REJECTED_BY_FIELD}",
		},
	)
	_upsert_cf(
		"Sales Invoice",
		{
			"fieldname": SALES_INVOICE_REJECTION_REASON_FIELD,
			"label": "Rejection Reason",
			"fieldtype": "Small Text",
			"insert_after": SALES_INVOICE_REJECTED_BY_FIELD,
			"depends_on": f"eval:doc.{SALES_INVOICE_REJECTED_BY_FIELD}",
			"read_only": 1,
		},
	)
