# Copyright (c) 2026, Titansoft Limited and contributors
"""Share Purchase Invoices with transporter suppliers on the portal.

CGM accountants raise a Purchase Invoice against a transporter (Supplier
with ``is_transporter``). Ticking **Share with Transporter** (or the form
button) makes that invoice visible on ``/transporter/invoices``.

The transporter sees what CGM still owes (``outstanding_amount``). When
CGM records a Payment Entry against the invoice, ERPNext sets the PI to
Paid and the portal shows Paid — no extra sync job.
"""

from __future__ import annotations

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

SHARE_FIELD = "custom_share_with_transporter"
SHARED_ON_FIELD = "custom_shared_with_transporter_on"
SUPPLIER_IS_TRANSPORTER_FIELD = "custom_supplier_is_transporter"
TRANSPORTER_PURCHASE_INVOICE_PRINT_FORMAT = "CGM Purchase Invoice Transporter"

_PDF_METHOD = (
	"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share"
	".download_shared_purchase_invoice_pdf"
)


def ensure_transporter_invoice_share_fields() -> None:
	"""Create Purchase Invoice custom fields used to share with the portal."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _ensure_cf

	_ensure_cf(
		"Purchase Invoice",
		{
			"fieldname": SUPPLIER_IS_TRANSPORTER_FIELD,
			"label": "Supplier Is Transporter",
			"fieldtype": "Check",
			"fetch_from": "supplier.is_transporter",
			"insert_after": "supplier_name",
			"read_only": 1,
			"hidden": 1,
			"print_hide": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
		},
	)
	_ensure_cf(
		"Purchase Invoice",
		{
			"fieldname": SHARE_FIELD,
			"label": "Share with Transporter",
			"fieldtype": "Check",
			"insert_after": SUPPLIER_IS_TRANSPORTER_FIELD,
			"allow_on_submit": 1,
			"no_copy": 1,
			"print_hide": 1,
			"in_standard_filter": 1,
			"depends_on": f"eval:doc.{SUPPLIER_IS_TRANSPORTER_FIELD}",
			"description": (
				"Show this invoice on the transporter portal so they can see "
				"what CGM owes them. When payment is recorded, they will see it as Paid."
			),
		},
	)
	_ensure_cf(
		"Purchase Invoice",
		{
			"fieldname": SHARED_ON_FIELD,
			"label": "Shared with Transporter On",
			"fieldtype": "Datetime",
			"insert_after": SHARE_FIELD,
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"print_hide": 1,
			"depends_on": f"eval:doc.{SHARE_FIELD}",
		},
	)
	_hide_internal_purchase_invoice_fields_from_print()
	ensure_transporter_purchase_invoice_print_format()
	frappe.clear_cache(doctype="Purchase Invoice")


def ensure_transporter_purchase_invoice_print_format() -> None:
	"""Install or refresh the transporter portal Purchase Invoice print format."""
	import json
	import os

	path = frappe.get_app_path(
		"cgm_shipping",
		"cgm_worldwide_shipping",
		"print_format",
		"cgm_purchase_invoice_transporter",
		"cgm_purchase_invoice_transporter.json",
	)
	if not os.path.exists(path):
		return

	with open(path, encoding="utf-8") as handle:
		data = json.load(handle)

	name = data.get("name") or TRANSPORTER_PURCHASE_INVOICE_PRINT_FORMAT
	fields = {
		"html": data.get("html"),
		"pdf_generator": data.get("pdf_generator") or "chrome",
		"custom_format": cint(data.get("custom_format", 1)),
		"disabled": cint(data.get("disabled", 0)),
		"doc_type": data.get("doc_type") or "Purchase Invoice",
		"module": data.get("module") or "CGM Worldwide Shipping",
		"print_format_type": data.get("print_format_type") or "Jinja",
		"standard": data.get("standard") or "No",
	}

	if frappe.db.exists("Print Format", name):
		doc = frappe.get_doc("Print Format", name)
		for key, value in fields.items():
			if value is not None:
				doc.set(key, value)
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc({"doctype": "Print Format", "name": name, **fields}).insert(
			ignore_permissions=True
		)

	frappe.db.commit()
	frappe.clear_cache(doctype="Print Format")


_PRINT_HIDE_PURCHASE_INVOICE_FIELDS = (
	"update_outstanding_for_self",
	"update_billed_amount_in_purchase_order",
	"update_billed_amount_in_purchase_receipt",
	"due_date",
)

_PRINT_SHOW_PURCHASE_INVOICE_FIELDS = ("posting_date",)


def _hide_internal_purchase_invoice_fields_from_print() -> None:
	"""Keep Standard print/preview focused on transporter-facing dates and fields."""
	meta = frappe.get_meta("Purchase Invoice")
	for fieldname in _PRINT_HIDE_PURCHASE_INVOICE_FIELDS:
		_set_purchase_invoice_print_hide(fieldname, hide=True)
	for fieldname in _PRINT_SHOW_PURCHASE_INVOICE_FIELDS:
		if meta.has_field(fieldname):
			_set_purchase_invoice_print_hide(fieldname, hide=False)


def _set_purchase_invoice_print_hide(fieldname: str, *, hide: bool) -> None:
	meta = frappe.get_meta("Purchase Invoice")
	if not meta.has_field(fieldname):
		return
	value = "1" if hide else "0"
	name = f"Purchase Invoice-{fieldname}-print_hide"
	if frappe.db.exists("Property Setter", name):
		if str(frappe.db.get_value("Property Setter", name, "value") or "") != value:
			frappe.db.set_value("Property Setter", name, "value", value, update_modified=False)
		return
	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"name": name,
			"doc_type": "Purchase Invoice",
			"doctype_or_field": "DocField",
			"field_name": fieldname,
			"property": "print_hide",
			"property_type": "Check",
			"value": value,
			"module": "CGM Worldwide Shipping",
		}
	).insert(ignore_permissions=True)


def supplier_is_transporter(supplier: str | None) -> bool:
	if not supplier:
		return False
	return bool(cint(frappe.db.get_value("Supplier", supplier, "is_transporter")))


def purchase_invoice_portal_status(status: str | None, outstanding_amount) -> dict:
	"""Portal status pill for a shared Purchase Invoice."""
	outstanding = flt(outstanding_amount)
	if outstanding <= 0 or status == "Paid":
		return {"label": _("Paid"), "tone": "success", "is_paid": True}
	if status and "Overdue" in str(status):
		return {"label": _("Overdue"), "tone": "danger", "is_paid": False}
	if status in ("Partly Paid", "Partly Paid and Discounted"):
		return {"label": _("Partly paid"), "tone": "active", "is_paid": False}
	return {"label": _("Unpaid"), "tone": "active", "is_paid": False}


def validate_share_with_transporter(doc, method=None) -> None:
	"""Keep the share flag valid: transporter supplier only, stamp shared-on."""
	if not doc.meta.has_field(SHARE_FIELD):
		return

	want_share = cint(doc.get(SHARE_FIELD))
	if doc.meta.has_field(SUPPLIER_IS_TRANSPORTER_FIELD):
		is_transporter = cint(doc.get(SUPPLIER_IS_TRANSPORTER_FIELD)) or supplier_is_transporter(
			doc.get("supplier")
		)
		doc.set(SUPPLIER_IS_TRANSPORTER_FIELD, 1 if is_transporter else 0)
	else:
		is_transporter = supplier_is_transporter(doc.get("supplier"))

	if want_share and not is_transporter:
		frappe.throw(
			_("Share with Transporter is only available when the supplier is a transporter."),
			title=_("Not a transporter"),
		)

	if want_share and cint(doc.get("is_return")):
		frappe.throw(
			_("Return purchase invoices cannot be shared with the transporter portal."),
			title=_("Cannot share return"),
		)

	if not doc.meta.has_field(SHARED_ON_FIELD):
		return

	if want_share:
		if not doc.get(SHARED_ON_FIELD):
			doc.set(SHARED_ON_FIELD, now_datetime())
	elif doc.get(SHARED_ON_FIELD):
		doc.set(SHARED_ON_FIELD, None)


def _assert_can_share_purchase_invoice(invoice_name: str) -> None:
	if not invoice_name or not frappe.db.exists("Purchase Invoice", invoice_name):
		frappe.throw(_("Purchase Invoice not found."))
	frappe.has_permission("Purchase Invoice", ptype="write", doc=invoice_name, throw=True)


@frappe.whitelist()
def share_purchase_invoice_with_transporter(purchase_invoice: str) -> dict:
	"""Accountant action: share a submitted PI with the transporter portal."""
	_assert_can_share_purchase_invoice(purchase_invoice)
	ensure_transporter_invoice_share_fields()

	row = frappe.db.get_value(
		"Purchase Invoice",
		purchase_invoice,
		["name", "supplier", "docstatus", "is_return", SHARE_FIELD],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Purchase Invoice not found."))
	if cint(row.docstatus) != 1:
		frappe.throw(_("Submit the Purchase Invoice before sharing it with the transporter."))
	if cint(row.is_return):
		frappe.throw(_("Return purchase invoices cannot be shared with the transporter portal."))
	if not supplier_is_transporter(row.supplier):
		frappe.throw(_("The supplier on this invoice is not a transporter."))

	when = now_datetime()
	frappe.db.set_value(
		"Purchase Invoice",
		purchase_invoice,
		{
			SHARE_FIELD: 1,
			SHARED_ON_FIELD: when,
			SUPPLIER_IS_TRANSPORTER_FIELD: 1,
		},
		update_modified=True,
	)
	return {
		"name": purchase_invoice,
		"shared": 1,
		"shared_on": when,
	}


def _pdf_url(name: str, disposition: str = "attachment") -> str:
	return (
		f"/api/method/{_PDF_METHOD}"
		+ f"?name={quote(name, safe='')}"
		+ f"&disposition={disposition}"
	)


def _project_ref(project_name: str | None) -> str:
	if not project_name:
		return ""
	from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal import (
		_project_display_ref,
	)

	return _project_display_ref(project_name)


def allocation_info_by_project(transporter: str, projects: list[str]) -> dict[str, dict]:
	"""Map project → allocation name + trucks offered (excluding withdrawn)."""
	if not transporter or not projects:
		return {}
	if not frappe.db.exists("DocType", "Container Allocation"):
		return {}

	from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
		OFFERED_TRUCK_WITHDRAWN,
	)

	unique_projects = list(dict.fromkeys(p for p in projects if p))
	if not unique_projects:
		return {}

	allocations = frappe.get_all(
		"Container Allocation",
		filters={
			"transporter": transporter,
			"project": ["in", unique_projects],
			"docstatus": 1,
		},
		fields=["name", "project"],
		order_by="allocation_date desc, modified desc",
		ignore_permissions=True,
	)
	by_project: dict[str, dict] = {}
	for row in allocations:
		if row.project not in by_project:
			by_project[row.project] = {
				"allocation": row.name,
				"trucks_offered": 0,
			}
	names = [info["allocation"] for info in by_project.values()]
	if not names or not frappe.db.exists("DocType", "Container Allocation Truck"):
		return by_project

	trucks = frappe.get_all(
		"Container Allocation Truck",
		filters={"parent": ["in", names], "status": ["!=", OFFERED_TRUCK_WITHDRAWN]},
		fields=["parent"],
		ignore_permissions=True,
	)
	counts: dict[str, int] = {}
	for truck in trucks:
		counts[truck.parent] = counts.get(truck.parent, 0) + 1
	for info in by_project.values():
		info["trucks_offered"] = counts.get(info["allocation"], 0)
	return by_project


def _portal_row(row: dict, allocation_info: dict | None = None) -> dict:
	status = purchase_invoice_portal_status(row.get("status"), row.get("outstanding_amount"))
	out = dict(row)
	out["tone"] = status["tone"]
	out["status_label"] = status["label"]
	out["is_paid"] = status["is_paid"]
	out["project_ref"] = _project_ref(row.get("project"))
	out["pdf_view_url"] = _pdf_url(row["name"], "inline")
	out["pdf_download_url"] = _pdf_url(row["name"], "attachment")
	out["outstanding_amount"] = flt(row.get("outstanding_amount"))
	out["grand_total"] = flt(row.get("grand_total"))
	info = allocation_info or {}
	allocation = info.get("allocation") or ""
	out["allocation_name"] = allocation
	out["allocation_url"] = (
		f"/transporter/allocation?name={quote(allocation, safe='')}" if allocation else ""
	)
	out["trucks_offered"] = cint(info.get("trucks_offered"))
	return out


def list_shared_purchase_invoices(transporter: str, limit: int = 200) -> list[dict]:
	"""Submitted PIs CGM has shared with this transporter supplier."""
	if not transporter:
		return []
	if not frappe.db.exists("DocType", "Purchase Invoice"):
		return []
	meta = frappe.get_meta("Purchase Invoice")
	if not meta.has_field(SHARE_FIELD):
		return []

	fields = [
		"name",
		"posting_date",
		"status",
		"grand_total",
		"outstanding_amount",
		"currency",
		"bill_no",
		"project",
		"supplier_name",
	]
	filters: dict = {
		"supplier": transporter,
		"docstatus": 1,
		SHARE_FIELD: 1,
	}
	if meta.has_field("is_return"):
		filters["is_return"] = 0

	rows = frappe.get_all(
		"Purchase Invoice",
		filters=filters,
		fields=fields,
		order_by="posting_date desc, creation desc",
		limit=limit,
		ignore_permissions=True,
	)
	projects = [r.get("project") for r in rows if r.get("project")]
	by_project = allocation_info_by_project(transporter, projects)
	return [_portal_row(row, by_project.get(row.get("project") or "")) for row in rows]


def get_transporter_invoice_summary(transporter: str) -> dict:
	"""Outstanding / paid totals for the transporter portal home and invoices page."""
	invoices = list_shared_purchase_invoices(transporter)
	outstanding_rows = [i for i in invoices if not i.get("is_paid")]
	paid_rows = [i for i in invoices if i.get("is_paid")]

	currency = ""
	if invoices:
		currency = invoices[0].get("currency") or ""
	if not currency:
		currency = frappe.defaults.get_global_default("currency") or ""

	total_outstanding = sum(flt(i.get("outstanding_amount")) for i in invoices)
	total_paid = sum(flt(i.get("grand_total")) for i in paid_rows)

	return {
		"invoices": invoices,
		"outstanding_invoices": outstanding_rows,
		"paid_invoices": paid_rows,
		"stat_invoice_count": len(invoices),
		"stat_outstanding_count": len(outstanding_rows),
		"stat_paid_count": len(paid_rows),
		"stat_outstanding_amount": total_outstanding,
		"stat_paid_amount": total_paid,
		"currency": currency,
	}


def _assert_shared_invoice_for_transporter(name: str, transporter: str) -> dict:
	if not name or not frappe.db.exists("Purchase Invoice", name):
		frappe.throw(_("Invoice not found."), frappe.DoesNotExistError)

	meta = frappe.get_meta("Purchase Invoice")
	fields = ["name", "supplier", "docstatus"]
	if meta.has_field(SHARE_FIELD):
		fields.append(SHARE_FIELD)
	if meta.has_field("is_return"):
		fields.append("is_return")

	row = frappe.db.get_value("Purchase Invoice", name, fields, as_dict=True)
	if not row:
		frappe.throw(_("Invoice not found."), frappe.DoesNotExistError)
	if row.supplier != transporter:
		frappe.throw(_("You do not have access to this invoice."), frappe.PermissionError)
	if cint(row.docstatus) != 1:
		frappe.throw(_("This invoice is not available."), frappe.PermissionError)
	if meta.has_field(SHARE_FIELD) and not cint(row.get(SHARE_FIELD)):
		frappe.throw(_("This invoice has not been shared with you."), frappe.PermissionError)
	if meta.has_field("is_return") and cint(row.get("is_return")):
		frappe.throw(_("This invoice is not available."), frappe.PermissionError)
	return row


@frappe.whitelist()
def get_my_purchase_invoices() -> dict:
	from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal import (
		require_transporter_portal_access,
	)

	transporter = require_transporter_portal_access()
	return get_transporter_invoice_summary(transporter)


@frappe.whitelist()
def download_shared_purchase_invoice_pdf(name: str, disposition: str = "attachment"):
	"""Stream a shared Purchase Invoice PDF to the owning transporter only."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal import (
		require_transporter_portal_access,
	)

	transporter = require_transporter_portal_access()
	_assert_shared_invoice_for_transporter(name, transporter)

	# Portal users have no desk Print permission. Ownership was already checked.
	doc = frappe.get_doc("Purchase Invoice", name, ignore_permissions=True)
	print_format = (
		TRANSPORTER_PURCHASE_INVOICE_PRINT_FORMAT
		if frappe.db.exists("Print Format", TRANSPORTER_PURCHASE_INVOICE_PRINT_FORMAT)
		else None
	)
	frappe.flags.ignore_print_permissions = True
	frappe.local.flags.ignore_print_permissions = True
	try:
		pdf = frappe.get_print(
			"Purchase Invoice",
			name,
			doc=doc,
			print_format=print_format,
			as_pdf=True,
		)
	finally:
		frappe.flags.ignore_print_permissions = False
		frappe.local.flags.ignore_print_permissions = False

	frappe.local.response.filename = f"{name}.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "pdf" if disposition == "inline" else "download"
