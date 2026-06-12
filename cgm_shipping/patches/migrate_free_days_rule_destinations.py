"""Migrate Shipping Line Free Days Rule: Default select → applies_to_all_destinations."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.shipping_line_rates import (
	FREE_DAYS_RULES_FIELD,
	get_valid_destinations,
)


def execute():
	if not frappe.db.exists("DocType", "Supplier"):
		return

	meta = frappe.get_meta("Supplier")
	if not meta.has_field(FREE_DAYS_RULES_FIELD):
		return

	child_meta = frappe.get_meta("Shipping Line Free Days Rule")
	has_checkbox = child_meta.has_field("applies_to_all_destinations")
	valid_destinations = {d.lower(): d for d in get_valid_destinations()}

	for supplier_name in frappe.get_all("Supplier", pluck="name"):
		supplier = frappe.get_doc("Supplier", supplier_name)
		changed = False
		for row in supplier.get(FREE_DAYS_RULES_FIELD) or []:
			region = (
				row.get("delivery_destination") or row.get("destination_region") or ""
			).strip()
			if not region:
				continue
			if region.lower() == "default":
				if has_checkbox:
					row.applies_to_all_destinations = 1
				row.delivery_destination = None
				if child_meta.has_field("destination_region"):
					row.destination_region = None
				changed = True
				continue
			canonical = valid_destinations.get(region.lower())
			if canonical and canonical != region:
				row.delivery_destination = canonical
				if child_meta.has_field("destination_region"):
					row.destination_region = None
				changed = True

		if changed:
			supplier.save(ignore_permissions=True)

	frappe.db.commit()
