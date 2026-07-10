"""Backfill KPA free-day date ranges and sync metrics after Free Days tab redesign."""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import getdate

from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	compute_container_metrics,
	get_default_kpa_free_days,
)

_METRIC_FIELDS = (
	"free_days",
	"kpa_free_days",
	"expected_empty_return",
	"port_days_used",
	"demurrage_days",
	"kpa_days",
	"days_outstanding",
	"status",
)


def execute():
	meta = frappe.get_meta("Container Tracker")
	if not meta.has_field("kpa_free_days_start_date"):
		return

	trackers = frappe.get_all(
		"Container Tracker",
		fields=["name"],
	)
	default_kpa = get_default_kpa_free_days()

	for row in trackers:
		data = frappe.get_doc("Container Tracker", row.name).as_dict()
		values: dict = {}
		anchor = data.get("discharging_date") or data.get("free_days_start_date")
		if anchor and not data.get("free_days_start_date"):
			values["free_days_start_date"] = anchor
		if anchor and not data.get("kpa_free_days_start_date"):
			values["kpa_free_days_start_date"] = anchor
		kpa_start = values.get("kpa_free_days_start_date") or data.get("kpa_free_days_start_date")
		if not data.get("kpa_free_days_end_date") and not values.get("kpa_free_days_end_date") and kpa_start:
			allowance = int(data.get("kpa_free_days") or default_kpa or 0)
			if allowance > 0:
				start = getdate(kpa_start)
				values["kpa_free_days_end_date"] = start + timedelta(days=allowance - 1)

		if not values:
			continue

		metrics = compute_container_metrics({**data, **values})
		for field in _METRIC_FIELDS:
			if field in metrics:
				values[field] = metrics[field]

		# Direct DB update avoids LinkValidationError on unrelated bad links
		# (e.g. delivery_location pointing at a missing Clearance Station).
		frappe.db.set_value("Container Tracker", row.name, values, update_modified=False)
