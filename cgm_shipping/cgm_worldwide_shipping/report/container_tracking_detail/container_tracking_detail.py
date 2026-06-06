# Copyright (c) 2026, Titansoft Limited and contributors

from __future__ import annotations

import frappe
from frappe import _
from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker import (
	enrich_container_row,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"fieldname": "container_tracker",
			"label": _("Container Tracker"),
			"fieldtype": "Link",
			"options": "Container Tracker",
			"width": 140,
		},
		{"fieldname": "project", "label": _("Project"), "fieldtype": "Link", "options": "Project", "width": 130},
		{"fieldname": "container_number", "label": _("Container No"), "fieldtype": "Data", "width": 120},
		{"fieldname": "bl_number", "label": _("B/L No"), "fieldtype": "Data", "width": 110},
		{"fieldname": "batch_bl_no", "label": _("Batch No"), "fieldtype": "Data", "width": 100},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "current_location", "label": _("Current Location"), "fieldtype": "Data", "width": 180},
		{"fieldname": "container_mode", "label": _("Mode"), "fieldtype": "Data", "width": 120},
		{"fieldname": "free_days", "label": _("Free Days"), "fieldtype": "Int", "width": 80},
		{"fieldname": "eta", "label": _("ETA"), "fieldtype": "Date", "width": 95},
		{"fieldname": "ata", "label": _("ATA"), "fieldtype": "Date", "width": 95},
		{"fieldname": "discharging_date", "label": _("Discharge"), "fieldtype": "Date", "width": 95},
		{"fieldname": "gate_out_date_port", "label": _("Gate Out"), "fieldtype": "Date", "width": 95},
		{"fieldname": "expected_empty_return", "label": _("Expected Return"), "fieldtype": "Date", "width": 110},
		{"fieldname": "actual_empty_return", "label": _("Actual Return"), "fieldtype": "Date", "width": 105},
		{"fieldname": "port_days_used", "label": _("Port Days"), "fieldtype": "Int", "width": 80},
		{"fieldname": "demurrage_days", "label": _("Demurrage Days"), "fieldtype": "Int", "width": 100},
		{"fieldname": "demurrage_amount", "label": _("Demurrage Amount"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "detention_days", "label": _("Detention Days"), "fieldtype": "Int", "width": 100},
		{"fieldname": "detention_amount", "label": _("Detention Amount"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "days_outstanding", "label": _("Days Overdue"), "fieldtype": "Int", "width": 100},
	]


def get_data(filters):
	conditions = []
	values = {}

	if filters.get("project"):
		conditions.append("ct.project = %(project)s")
		values["project"] = filters.project

	where = f"where {' and '.join(conditions)}" if conditions else ""

	rows = frappe.db.sql(
		f"""
		select
			ct.name as container_tracker,
			ct.project,
			ct.container_number,
			ct.bl_number,
			ct.batch_bl_no,
			ct.container_mode,
			ct.delivery_location,
			ct.eta,
			ct.ata,
			ct.discharging_date,
			ct.icd_mombasa_discharge_date,
			ct.custom_release_date,
			ct.gate_out_date_port,
			ct.delivery_date,
			ct.actual_empty_return,
			ct.expected_empty_return,
			ct.gate_in_date_depot,
			ct.icd_gate_in_date,
			ct.icd_gate_out_date,
			ct.free_days,
			ct.port_days_used,
			ct.daily_demurrage_rate,
			ct.daily_detention_rate,
			ct.demurrage_days,
			ct.detention_days,
			ct.demurrage_amount,
			ct.detention_amount,
			ct.demurrage_date,
			ct.days_outstanding,
			ct.status
		from `tabContainer Tracker` ct
		{where}
		order by ct.project asc, ct.container_number asc
		""",
		values,
		as_dict=True,
	)

	data = []
	for row in rows:
		enriched = enrich_container_row(row)
		enriched["status"] = enriched.get("status") or row.status or ""
		data.append(enriched)

	if filters.get("status"):
		data = [r for r in data if r.get("status") == filters.status]

	if filters.get("overdue_only"):
		data = [r for r in data if r.get("status") == "Overdue"]

	if filters.get("min_demurrage_days"):
		min_days = int(filters.min_demurrage_days)
		data = [r for r in data if (r.get("demurrage_days") or 0) >= min_days]

	return data
