# Copyright (c) 2026, Titansoft Limited and contributors

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, getdate

from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker import (
	enrich_container_row,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"fieldname": "container_number", "label": _("Container Number"), "fieldtype": "Data", "width": 110},
		{"fieldname": "cgm_ref_no", "label": _("Project (CGM Ref No)"), "fieldtype": "Data", "width": 130},
		{"fieldname": "customer_name", "label": _("Customer"), "fieldtype": "Data", "width": 120},
		{"fieldname": "bl_number", "label": _("B/L Number"), "fieldtype": "Data", "width": 100},
		{"fieldname": "discharging_date", "label": _("Gate In Port"), "fieldtype": "Date", "width": 95},
		{"fieldname": "free_days", "label": _("Free Days"), "fieldtype": "Int", "width": 80},
		{"fieldname": "free_days_expire", "label": _("Free Days Expire"), "fieldtype": "Date", "width": 105},
		{"fieldname": "gate_out_date_port", "label": _("Gate Out Port"), "fieldtype": "Date", "width": 95},
		{"fieldname": "port_days_used", "label": _("Days In Port"), "fieldtype": "Int", "width": 90},
		{"fieldname": "demurrage_days", "label": _("Demurrage Days"), "fieldtype": "Int", "width": 100},
		{"fieldname": "demurrage_amount", "label": _("Demurrage Amount (USD)"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "kpa_days", "label": _("KPA Days"), "fieldtype": "Int", "width": 80},
		{"fieldname": "kpa_amount", "label": _("KPA Amount"), "fieldtype": "Currency", "width": 100},
		{"fieldname": "truck_number", "label": _("Truck Number"), "fieldtype": "Data", "width": 100},
		{"fieldname": "driver_name", "label": _("Driver Name"), "fieldtype": "Data", "width": 110},
		{"fieldname": "driver_contact", "label": _("Driver Contact"), "fieldtype": "Data", "width": 110},
		{"fieldname": "transporter_name", "label": _("Transporter"), "fieldtype": "Data", "width": 120},
		{"fieldname": "gate_in_date_warehouse", "label": _("Date Arrived Warehouse"), "fieldtype": "Date", "width": 120},
		{"fieldname": "offloading_date", "label": _("Date Offloaded"), "fieldtype": "Date", "width": 105},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 130},
		{"fieldname": "alert_status", "label": _("Alert Status"), "fieldtype": "Data", "width": 160},
		{"fieldname": "expected_empty_return", "label": _("Expected Return Date"), "fieldtype": "Date", "width": 115},
		{"fieldname": "actual_empty_return", "label": _("Actual Return Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "detention_days", "label": _("Detention Days"), "fieldtype": "Int", "width": 100},
		{"fieldname": "detention_amount", "label": _("Detention Amount (USD)"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "days_outstanding", "label": _("Days Outstanding"), "fieldtype": "Int", "width": 110},
	]


CONTAINER_FIELDS = [
	"name",
	"project",
	"container_number",
	"bl_number",
	"shipping_line",
	"transporter",
	"driver_name",
	"driver_contact",
	"discharging_date",
	"free_days",
	"gate_out_date_port",
	"port_days_used",
	"demurrage_days",
	"demurrage_amount",
	"kpa_days",
	"kpa_amount",
	"truck_number",
	"gate_in_date_warehouse",
	"offloading_date",
	"status",
	"expected_empty_return",
	"actual_empty_return",
	"detention_days",
	"detention_amount",
	"days_outstanding",
]


def _row_style(alert_status: str, status: str) -> str:
	alert = alert_status or ""
	if "🔴" in alert or "🚨" in alert or status == "Return Overdue":
		return "background-color:#fde2e2;"
	if "⚠️" in alert:
		return "background-color:#fff3cd;"
	if "✅" in alert or status in ("Empty Returned", "Interchange Received"):
		return "background-color:#d4edda;"
	return ""


def get_data(filters):
	list_filters = {}
	if filters.get("project"):
		list_filters["project"] = filters.project
	if filters.get("shipping_line"):
		list_filters["shipping_line"] = filters.shipping_line
	if filters.get("status"):
		list_filters["status"] = filters.status

	rows = frappe.get_list(
		"Container Tracker",
		filters=list_filters,
		fields=CONTAINER_FIELDS,
		order_by="project asc, container_number asc",
		limit_page_length=0,
	)

	from_date = getdate(filters.from_date) if filters.get("from_date") else None
	to_date = getdate(filters.to_date) if filters.get("to_date") else None
	data = []

	for row in rows:
		enriched = enrich_container_row(row)
		discharge = getdate(enriched.get("discharging_date"))
		if from_date and discharge and discharge < from_date:
			continue
		if to_date and discharge and discharge > to_date:
			continue

		if filters.get("show_only_active") and enriched.get("status") == "Interchange Received":
			continue
		if filters.get("show_only_alerts") and not enriched.get("alert_status"):
			continue

		project_doc = frappe.db.get_value(
			"Project",
			enriched.get("project"),
			["custom_cgm_ref_no", "customer"],
			as_dict=True,
		) or {}
		enriched["cgm_ref_no"] = project_doc.get("custom_cgm_ref_no") or enriched.get("project")
		customer = project_doc.get("customer")
		enriched["customer_name"] = (
			frappe.db.get_value("Customer", customer, "customer_name") if customer else ""
		)

		transporter = enriched.get("transporter")
		enriched["transporter_name"] = (
			frappe.db.get_value("Supplier", transporter, "supplier_name") if transporter else ""
		)

		if discharge and enriched.get("free_days"):
			enriched["free_days_expire"] = add_days(discharge, int(enriched.get("free_days") or 0))
		else:
			enriched["free_days_expire"] = None

		enriched["row_style"] = _row_style(
			enriched.get("alert_status") or "", enriched.get("status") or ""
		)
		data.append(enriched)

	return data
