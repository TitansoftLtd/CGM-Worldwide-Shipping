"""Enable Allows Amendment Invoices on seeded Clearance Charge Item invoice rows."""

from __future__ import annotations

import frappe
from frappe.utils import cint


def execute() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.clearance_charge_item import (
		DEFAULT_CLEARANCE_CHARGE_ITEMS,
		LINE_INVOICE,
		ensure_clearance_charge_items,
		repair_clearance_charge_item_setup,
	)

	if not frappe.db.exists("DocType", "Clearance Charge Item"):
		return

	frappe.reload_doctype("Clearance Charge Item", force=True)
	if not frappe.get_meta("Clearance Charge Item").has_field("allows_amendment"):
		return

	ensure_clearance_charge_items()

	updated = 0
	for spec in DEFAULT_CLEARANCE_CHARGE_ITEMS:
		if (spec.get("line_type") or "") != LINE_INVOICE:
			continue
		if not cint(spec.get("allows_amendment")):
			continue
		name = (spec.get("charge_name") or "").strip()
		if not name or not frappe.db.exists("Clearance Charge Item", name):
			continue
		if cint(frappe.db.get_value("Clearance Charge Item", name, "allows_amendment")):
			continue
		frappe.db.set_value(
			"Clearance Charge Item",
			name,
			"allows_amendment",
			1,
			update_modified=False,
		)
		updated += 1

	repair_clearance_charge_item_setup()
	if updated:
		frappe.db.commit()
		print(f"Enabled allows_amendment on {updated} Clearance Charge Item(s)")
