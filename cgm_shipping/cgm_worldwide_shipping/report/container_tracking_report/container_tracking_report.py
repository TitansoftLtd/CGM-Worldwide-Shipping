# Copyright (c) 2026, Titansoft Limited and contributors

from __future__ import annotations

from collections import Counter

import frappe
from frappe import _
from frappe.utils import getdate

from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
	display_ref_from_values,
)
from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker import (
	enrich_container_row,
)

EXPANDED_COLUMNS = [
	{"fieldname": "demurrage_days", "label": _("Demurrage/Detention Days"), "fieldtype": "Int", "width": 130},
	{"fieldname": "kpa_days", "label": _("KPA Days"), "fieldtype": "Int", "width": 80},
	{"fieldname": "days_outstanding", "label": _("Days Outstanding"), "fieldtype": "Int", "width": 110},
	{"fieldname": "seal_no", "label": _("Seal Number"), "fieldtype": "Data", "width": 90},
	{"fieldname": "type_of_container", "label": _("Type of Container"), "fieldtype": "Data", "width": 100},
]

CONTAINER_FIELDS = [
	"name",
	"project",
	"container_number",
	"type_of_container",
	"bl_number",
	"shipping_line",
	"transporter",
	"driver_name",
	"driver_contact",
	"discharging_date",
	"gate_out_date_port",
	"truck_number",
	"gate_in_date_warehouse",
	"delivery_location",
	"offloading_date",
	"status",
	"expected_empty_return",
	"actual_empty_return",
	"demurrage_days",
	"demurrage_amount",
	"kpa_days",
	"kpa_amount",
	"days_outstanding",
	"seal_no",
]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	station_label = _resolve_station_header_label(filters)
	columns = _build_columns(station_label, filters)
	return columns, get_data(filters, station_label)


def _resolve_station_header_label(filters) -> str:
	if filters.get("clearance_station"):
		return filters.clearance_station
	return "Warehouse"


def _build_columns(station_label: str, filters) -> list[dict]:
	columns = [
		{"fieldname": "container_number", "label": _("Container"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "discharging_date",
			"label": _("Gate In MBA"),
			"fieldtype": "Date",
			"width": 95,
		},
		{
			"fieldname": "gate_out_date_port",
			"label": _("Gate Out MBA"),
			"fieldtype": "Date",
			"width": 95,
		},
		{"fieldname": "truck_number", "label": _("Truck No"), "fieldtype": "Data", "width": 100},
		{
			"fieldname": "contact_info",
			"label": _("Contact Info"),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "gate_in_date_warehouse",
			"label": _("Date Gate In {0}").format(station_label),
			"fieldtype": "Date",
			"width": 130,
		},
		{
			"fieldname": "offloading_date",
			"label": _("Date Offloaded at {0}").format(station_label),
			"fieldtype": "Date",
			"width": 140,
		},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "actual_empty_return",
			"label": _("Actual Return Date"),
			"fieldtype": "Date",
			"width": 115,
		},
		{
			"fieldname": "expected_empty_return",
			"label": _("Expected Return Date"),
			"fieldtype": "Date",
			"width": 120,
		},
		{"fieldname": "transporter_name", "label": _("Transporter"), "fieldtype": "Data", "width": 120},
	]
	if frappe.utils.cint(filters.get("show_expanded")):
		columns.extend(EXPANDED_COLUMNS)
	return columns


def _row_style(status: str, demurrage_days: int, days_outstanding: int) -> str:
	status = status or ""
	if "Overdue" in status or (demurrage_days or 0) > 0:
		return "background-color:#fde2e2;"
	if (days_outstanding or 0) > 0:
		return "background-color:#fff3cd;"
	if status == "Interchange Received":
		return "background-color:#d4edda;"
	return ""


def _contact_info(row: dict) -> str:
	parts = [row.get("driver_name") or "", row.get("driver_contact") or ""]
	return " ".join(p for p in parts if p).strip()


def _project_group_header_fields() -> list[str]:
	"""Project columns for B/L group headers — skip fields missing on this site."""
	meta = frappe.get_meta("Project")
	fields = ["name", "project_name"]
	for fieldname in ("custom_project_reference", "custom_cgm_ref_no", "custom_batch_no"):
		if meta.has_field(fieldname):
			fields.append(fieldname)
	return fields


def get_data(filters, station_label: str | None = None):
	list_filters = {}
	if filters.get("project"):
		list_filters["project"] = filters.project
	if filters.get("shipping_line"):
		list_filters["shipping_line"] = filters.shipping_line
	if filters.get("status"):
		list_filters["status"] = filters.status
	if filters.get("clearance_station"):
		list_filters["delivery_location"] = filters.clearance_station

	rows = frappe.get_list(
		"Container Tracker",
		filters=list_filters,
		fields=CONTAINER_FIELDS,
		order_by="project asc, bl_number asc, container_number asc",
		limit_page_length=0,
	)

	from_date = getdate(filters.from_date) if filters.get("from_date") else None
	to_date = getdate(filters.to_date) if filters.get("to_date") else None
	bl_filter = (filters.get("bl_number") or "").strip()

	enriched_rows = []
	for row in rows:
		enriched = enrich_container_row(row)
		if bl_filter and bl_filter.lower() not in (enriched.get("bl_number") or "").lower():
			continue
		discharge = getdate(enriched.get("discharging_date"))
		if from_date and discharge and discharge < from_date:
			continue
		if to_date and discharge and discharge > to_date:
			continue
		if frappe.utils.cint(filters.get("show_only_active")) and enriched.get("status") == "Interchange Received":
			continue
		enriched_rows.append(enriched)

	if not station_label:
		station_label = _most_common_station(enriched_rows)

	data: list[dict] = []
	current_key = None
	group_demurrage = 0.0

	for enriched in enriched_rows:
		project = enriched.get("project")
		bl_number = enriched.get("bl_number") or ""
		group_key = (project, bl_number)

		if group_key != current_key:
			if current_key is not None:
				data.append(_subtotal_row(group_demurrage))
			current_key = group_key
			group_demurrage = 0.0
			project_doc = frappe.db.get_value(
				"Project",
				project,
				_project_group_header_fields(),
				as_dict=True,
			) or {}
			project_ref = display_ref_from_values(project_doc)
			data.append(
				{
					"container_number": _(
						"B/L: {0}    BATCH: {1}    REF: {2}"
					).format(
						bl_number or "—",
						project_doc.get("custom_batch_no") or "—",
						project_ref or "—",
					),
					"is_group_header": 1,
					"row_style": "font-weight:bold;background-color:#eef2ff;",
				}
			)

		transporter = enriched.get("transporter")
		enriched["transporter_name"] = (
			frappe.db.get_value("Supplier", transporter, "supplier_name") if transporter else ""
		)
		enriched["contact_info"] = _contact_info(enriched)
		enriched["row_style"] = _row_style(
			enriched.get("status") or "",
			enriched.get("demurrage_days") or 0,
			enriched.get("days_outstanding") or 0,
		)
		group_demurrage += enriched.get("demurrage_days") or 0
		data.append(enriched)

	if current_key is not None:
		data.append(_subtotal_row(group_demurrage))

	return data


def _subtotal_row(demurrage: float) -> dict:
	return {
		"container_number": _("Subtotal"),
		"demurrage_days": demurrage,
		"is_subtotal": 1,
		"row_style": "font-weight:bold;background-color:#f8f9fa;",
	}


def _most_common_station(rows: list[dict]) -> str:
	counter: Counter[str] = Counter()
	for row in rows:
		station = (row.get("delivery_location") or "").strip()
		if station:
			counter[station] += 1
	return counter.most_common(1)[0][0] if counter else "Warehouse"
