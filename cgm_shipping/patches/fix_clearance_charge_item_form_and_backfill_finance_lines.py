"""Repair Clearance Charge Item form caches and backfill Task Finance Line links."""

from __future__ import annotations

import frappe


def execute() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.clearance_charge_item import (
		repair_clearance_charge_item_setup,
	)

	result = repair_clearance_charge_item_setup()
	if any(result.values()):
		frappe.db.commit()
		print(
			"Clearance Charge Item repair:",
			f"created={result['created_charge_items']},",
			f"backfilled={result['backfilled_charge_links']},",
			f"synced={result['synced_finance_lines']}",
		)
