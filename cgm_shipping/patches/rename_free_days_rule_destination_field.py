"""Rename Shipping Line Free Days Rule.destination_region → delivery_destination."""

from __future__ import annotations

import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	if not frappe.db.exists("DocType", "Shipping Line Free Days Rule"):
		return

	meta = frappe.get_meta("Shipping Line Free Days Rule")
	if not meta.has_field("delivery_destination"):
		return
	if not frappe.db.has_column("Shipping Line Free Days Rule", "destination_region"):
		return

	rename_field(
		"Shipping Line Free Days Rule",
		"destination_region",
		"delivery_destination",
	)
	frappe.clear_cache(doctype="Shipping Line Free Days Rule")
