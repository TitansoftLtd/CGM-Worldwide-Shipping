# Copyright (c) 2026, Titansoft Limited and contributors
"""Share Sales Invoices with the customer on the portal.

Ticking **Share with Customer** (or the form button) makes a submitted
Sales Invoice visible on ``/my-invoices``. Credit notes cannot be shared.

The customer sees outstanding in invoice currency. When CGM records a
Payment Entry, ERPNext sets the invoice to Paid and the portal shows
Paid — no extra sync job.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

SHARE_FIELD = "custom_share_with_customer"
SHARED_ON_FIELD = "custom_shared_with_customer_on"


def ensure_customer_invoice_share_fields() -> None:
	"""Create Sales Invoice custom fields used to share with the portal."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _ensure_cf

	_ensure_cf(
		"Sales Invoice",
		{
			"fieldname": SHARE_FIELD,
			"label": "Share with Customer",
			"fieldtype": "Check",
			"insert_after": "customer_name",
			"allow_on_submit": 1,
			"no_copy": 1,
			"print_hide": 1,
			"in_standard_filter": 1,
			"description": (
				"Show this invoice on the customer portal. "
				"When payment is recorded, they will see it as Paid."
			),
		},
	)
	_ensure_cf(
		"Sales Invoice",
		{
			"fieldname": SHARED_ON_FIELD,
			"label": "Shared with Customer On",
			"fieldtype": "Datetime",
			"insert_after": SHARE_FIELD,
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"print_hide": 1,
			"depends_on": f"eval:doc.{SHARE_FIELD}",
		},
	)
	frappe.clear_cache(doctype="Sales Invoice")


def validate_share_with_customer(doc, method=None) -> None:
	"""Keep the share flag valid: no credit notes, stamp shared-on."""
	if not doc.meta.has_field(SHARE_FIELD):
		return

	want_share = cint(doc.get(SHARE_FIELD))
	if want_share and cint(doc.get("is_return")):
		frappe.throw(
			_("Credit notes cannot be shared with the customer portal."),
			title=_("Cannot share return"),
		)

	if not doc.meta.has_field(SHARED_ON_FIELD):
		return

	if want_share:
		if not doc.get(SHARED_ON_FIELD):
			doc.set(SHARED_ON_FIELD, now_datetime())
	elif doc.get(SHARED_ON_FIELD):
		doc.set(SHARED_ON_FIELD, None)


def _assert_can_share_sales_invoice(invoice_name: str) -> None:
	if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
		frappe.throw(_("Sales Invoice not found."))
	frappe.has_permission("Sales Invoice", ptype="write", doc=invoice_name, throw=True)


@frappe.whitelist()
def set_sales_invoice_customer_share(sales_invoice: str, share: int | str | None = None) -> dict:
	"""Set or clear Share with Customer on a submitted Sales Invoice."""
	_assert_can_share_sales_invoice(sales_invoice)
	ensure_customer_invoice_share_fields()

	row = frappe.db.get_value(
		"Sales Invoice",
		sales_invoice,
		["name", "customer", "docstatus", "is_return", SHARE_FIELD, SHARED_ON_FIELD],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Sales Invoice not found."))
	if cint(row.docstatus) != 1:
		frappe.throw(_("Submit the Sales Invoice before sharing it with the customer."))
	if cint(row.is_return):
		frappe.throw(_("Credit notes cannot be shared with the customer portal."))
	if not row.customer:
		frappe.throw(_("This invoice has no customer."))

	want_share = cint(share) if share is not None else 1
	if want_share:
		when = row.get(SHARED_ON_FIELD) or now_datetime()
	else:
		when = None

	frappe.db.set_value(
		"Sales Invoice",
		sales_invoice,
		{
			SHARE_FIELD: want_share,
			SHARED_ON_FIELD: when,
		},
		update_modified=True,
	)
	return {
		"name": sales_invoice,
		"shared": want_share,
		"shared_on": when,
	}


@frappe.whitelist()
def share_sales_invoice_with_customer(sales_invoice: str) -> dict:
	"""Accountant action: share a submitted SI with the customer portal."""
	return set_sales_invoice_customer_share(sales_invoice, share=1)


def assert_shared_sales_invoice_for_customer(name: str, customer: str) -> dict:
	"""Raise if this submitted, shared invoice does not belong to the customer."""
	if not name or not frappe.db.exists("Sales Invoice", name):
		frappe.throw(_("Invoice not found."), frappe.DoesNotExistError)

	meta = frappe.get_meta("Sales Invoice")
	fields = ["name", "customer", "docstatus"]
	if meta.has_field(SHARE_FIELD):
		fields.append(SHARE_FIELD)
	if meta.has_field("is_return"):
		fields.append("is_return")

	row = frappe.db.get_value("Sales Invoice", name, fields, as_dict=True)
	if not row:
		frappe.throw(_("Invoice not found."), frappe.DoesNotExistError)
	if row.customer != customer:
		frappe.throw(_("You do not have access to this invoice."), frappe.PermissionError)
	if cint(row.docstatus) != 1:
		frappe.throw(_("This invoice is not available."), frappe.PermissionError)
	if meta.has_field(SHARE_FIELD) and not cint(row.get(SHARE_FIELD)):
		frappe.throw(_("This invoice has not been shared with you."), frappe.PermissionError)
	if meta.has_field("is_return") and cint(row.get("is_return")):
		frappe.throw(_("This invoice is not available."), frappe.PermissionError)
	return row
