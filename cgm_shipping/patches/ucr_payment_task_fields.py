"""Custom fields on Task for UCR invoice → payment → receipt workflow."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	_create_cf,
)


def execute():
	_create_cf(
		"Task",
		{
			"fieldname": "custom_ucr_invoice_submitted",
			"label": "UCR Invoice Submitted to Finance",
			"fieldtype": "Check",
			"insert_after": "custom_permit_invoices_submitted",
			"read_only": 1,
			"default": "0",
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_section_ucr_payment",
			"label": "UCR Payment",
			"fieldtype": "Section Break",
			"insert_after": "custom_payment_entry",
			"collapsible": 0,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_ucr_invoice_verified",
			"label": "UCR Invoice Verified",
			"fieldtype": "Check",
			"insert_after": "custom_section_ucr_payment",
			"description": "Finance confirms the UCR invoice from the declarant task.",
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_ucr_payment_receipt",
			"label": "UCR Payment Receipt",
			"fieldtype": "Attach",
			"insert_after": "custom_ucr_invoice_verified",
			"description": "Proof of payment after Finance records PI and Payment Entry.",
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_ucr_receipt_verified",
			"label": "UCR Receipt Verified",
			"fieldtype": "Check",
			"insert_after": "custom_ucr_payment_receipt",
			"description": "Finance confirms the payment receipt before completing this task.",
		},
	)
	frappe.clear_cache(doctype="Task")
	frappe.db.commit()
