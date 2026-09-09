"""Submit Sales Invoices stuck at Approved (draft) so ERPNext status can apply."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SALES_INVOICE_WORKFLOW_STATE_APPROVED,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sales_invoice import (
	ensure_approved_sales_invoice_submitted,
)
from cgm_shipping.patches.ensure_sales_invoice_workflow import (
	_sync_workflow,
)


def execute() -> None:
	_sync_workflow()

	names = frappe.get_all(
		"Sales Invoice",
		filters={
			"docstatus": 0,
			"workflow_state": SALES_INVOICE_WORKFLOW_STATE_APPROVED,
		},
		pluck="name",
	)
	for name in names:
		doc = frappe.get_doc("Sales Invoice", name)
		try:
			ensure_approved_sales_invoice_submitted(doc)
		except Exception:
			frappe.log_error(
				title=f"CGM: could not submit stuck Sales Invoice {name}",
				message=frappe.get_traceback(),
			)
			frappe.db.set_value(
				"Sales Invoice",
				name,
				"workflow_state",
				"Pending Approval",
				update_modified=False,
			)

	frappe.db.commit()
