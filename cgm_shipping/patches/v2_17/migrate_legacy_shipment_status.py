"""Migrate legacy Project shipment statuses to the new CGM Sea chart values."""

from __future__ import annotations

import frappe


LEGACY_STATUS_MAP: dict[str, str] = {
	"IDF Created": "UCR Applied",
	"Permits Processing": "Pre-clearance",
	"Awaiting Arrival": "Client Inspection",
}


def execute():
	if not frappe.db.exists("Custom Field", "Project-custom_shipment_status"):
		return

	for legacy, mapped in LEGACY_STATUS_MAP.items():
		frappe.db.sql(
			"""
			UPDATE `tabProject`
			SET custom_shipment_status = %s
			WHERE custom_shipment_status = %s
			""",
			(mapped, legacy),
		)

	frappe.db.commit()
	frappe.clear_cache(doctype="Project")

