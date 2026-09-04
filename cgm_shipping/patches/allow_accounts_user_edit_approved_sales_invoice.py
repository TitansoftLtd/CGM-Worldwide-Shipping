"""Let Accounts Users edit allow-on-submit fields on submitted Sales Invoices."""

from __future__ import annotations

import frappe

from cgm_shipping.patches.ensure_sales_invoice_workflow import _sync_workflow


def execute() -> None:
	if not frappe.db.exists("DocType", "Workflow"):
		return
	_sync_workflow()
	frappe.db.commit()
