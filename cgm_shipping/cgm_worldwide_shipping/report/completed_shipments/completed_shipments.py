"""Shipments that finished inside a date range.

Answers "which shipments completed in September", which the Project list could not:
`custom_shipment_status` says a shipment is finished but not when, so a finished
shipment from two years ago sat beside one finished yesterday.

Only shipments with a completion date appear. One still in progress has no date and is
left out, which is the point of the report rather than a gap in it.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	COMPLETED_SHIPMENT_STATUSES,
)


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})

	if not filters.from_date or not filters.to_date:
		frappe.throw(_("From Date and To Date are both required."))
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date."))

	return get_columns(), get_data(filters)


def get_columns() -> list[dict]:
	return [
		{"label": _("Shipment"), "fieldname": "name", "fieldtype": "Link", "options": "Project", "width": 150},
		{"label": _("Shipment Name"), "fieldname": "project_name", "fieldtype": "Data", "width": 220},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("Shipment Type"), "fieldname": "shipment_type", "fieldtype": "Link", "options": "Shipment Type", "width": 130},
		{"label": _("Status"), "fieldname": "shipment_status", "fieldtype": "Data", "width": 100},
		{"label": _("Opened"), "fieldname": "opened_date", "fieldtype": "Date", "width": 100},
		{"label": _("Completed"), "fieldname": "completion_date", "fieldtype": "Date", "width": 100},
		# How long the shipment took, which is the question that follows "when did it finish".
		{"label": _("Days Taken"), "fieldname": "days_taken", "fieldtype": "Int", "width": 95},
	]


def get_data(filters) -> list[dict]:
	conditions = {
		"custom_completion_date": ["between", [filters.from_date, filters.to_date]],
	}
	if filters.get("customer"):
		conditions["customer"] = filters.customer
	if filters.get("shipment_type"):
		conditions["custom_shipment_type"] = filters.shipment_type
	if filters.get("shipment_status"):
		conditions["custom_shipment_status"] = filters.shipment_status
	else:
		conditions["custom_shipment_status"] = ["in", sorted(COMPLETED_SHIPMENT_STATUSES)]

	rows = frappe.get_all(
		"Project",
		filters=conditions,
		fields=[
			"name",
			"project_name",
			"customer",
			"custom_shipment_type as shipment_type",
			"custom_shipment_status as shipment_status",
			"custom_opened_date as opened_date",
			"custom_completion_date as completion_date",
		],
		order_by="custom_completion_date desc, name desc",
	)

	for row in rows:
		row["days_taken"] = (
			date_diff(row.completion_date, row.opened_date)
			if row.opened_date and row.completion_date
			else None
		)

	return rows
