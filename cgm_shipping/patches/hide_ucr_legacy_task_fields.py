"""Hide legacy UCR Payment fields on Task - verification uses Invoices & Receipts table."""
from __future__ import annotations

import frappe

HIDDEN_FIELDS = (
	"custom_section_ucr_payment",
	"custom_ucr_invoice_verified",
	"custom_ucr_payment_receipt",
	"custom_ucr_receipt_verified",
)


def execute():
	for fieldname in HIDDEN_FIELDS:
		cf_name = f"Task-{fieldname}"
		if frappe.db.exists("Custom Field", cf_name):
			frappe.db.set_value("Custom Field", cf_name, "hidden", 1, update_modified=False)
	frappe.clear_cache(doctype="Task")
