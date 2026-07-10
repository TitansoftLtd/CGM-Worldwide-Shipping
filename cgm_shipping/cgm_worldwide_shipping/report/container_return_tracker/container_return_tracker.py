# Copyright (c) 2026, Titansoft Limited and contributors

from __future__ import annotations

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.container_ops_board import (
	get_container_return_tracker,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_container_return_tracker(filters).get("rows") or []
	return columns, data


def get_columns():
	return [
		{
			"fieldname": "container_number",
			"label": _("Container No"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "project_ref",
			"label": _("Shipment Ref"),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "project",
			"label": _("Project"),
			"fieldtype": "Link",
			"options": "Project",
			"width": 120,
		},
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Data", "width": 160},
		{
			"fieldname": "clearance_station",
			"label": _("Clearance Station"),
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"fieldname": "gate_out_date_port",
			"label": _("Gate Out / Dispatch"),
			"fieldtype": "Date",
			"width": 120,
		},
		{
			"fieldname": "expected_empty_return",
			"label": _("Expected Return"),
			"fieldtype": "Date",
			"width": 120,
		},
		{
			"fieldname": "actual_empty_return",
			"label": _("Actual Return"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "days_outstanding",
			"label": _("Days Outstanding"),
			"fieldtype": "Int",
			"width": 120,
		},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 140},
	]
