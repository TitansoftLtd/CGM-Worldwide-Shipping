"""Copy destination_region → delivery_destination on Shipping Line Free Days Rule rows."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.shipping_line_rates import (
	FREE_DAYS_RULES_FIELD,
	get_valid_destinations,
)


def execute():
	if not frappe.db.table_exists("Shipping Line Free Days Rule"):
		return

	table = "`tabShipping Line Free Days Rule`"
	has_old = frappe.db.has_column("Shipping Line Free Days Rule", "destination_region")
	has_new = frappe.db.has_column("Shipping Line Free Days Rule", "delivery_destination")

	if has_old and has_new:
		frappe.db.sql(
			f"""
			UPDATE {table}
			SET delivery_destination = destination_region
			WHERE IFNULL(delivery_destination, '') = ''
			  AND IFNULL(destination_region, '') != ''
			"""
		)

	if not frappe.db.exists("DocType", "Supplier"):
		return

	meta = frappe.get_meta("Supplier")
	if not meta.has_field(FREE_DAYS_RULES_FIELD):
		return

	valid_destinations = {d.lower(): d for d in get_valid_destinations()}
	child_meta = frappe.get_meta("Shipping Line Free Days Rule")
	has_delivery_field = child_meta.has_field("delivery_destination")

	for supplier_name in frappe.get_all("Supplier", pluck="name"):
		supplier = frappe.get_doc("Supplier", supplier_name)
		changed = False
		for row in supplier.get(FREE_DAYS_RULES_FIELD) or []:
			if has_delivery_field:
				dest = (row.get("delivery_destination") or row.get("destination_region") or "").strip()
			else:
				dest = (row.get("destination_region") or "").strip()

			if not dest:
				continue
			if dest.lower() == "default":
				if child_meta.has_field("applies_to_all_destinations"):
					row.applies_to_all_destinations = 1
				if has_delivery_field:
					row.delivery_destination = None
				if hasattr(row, "destination_region"):
					row.destination_region = None
				changed = True
				continue

			canonical = valid_destinations.get(dest.lower())
			if canonical and canonical != dest and has_delivery_field:
				row.delivery_destination = canonical
				changed = True

		if changed:
			supplier.save(ignore_permissions=True)

	frappe.db.commit()
