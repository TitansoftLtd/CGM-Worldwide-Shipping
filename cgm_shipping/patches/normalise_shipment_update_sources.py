"""Fold retired Shipment Update sources into Internal.

`update_source` shipped with Customs, Finance and Other alongside Customer,
Transporter and Internal. Nothing ever wrote the first three - they were not
reachable from any portal or Desk action - so they only widened a filter that
could never match. Any row still carrying one is CGM's own message, which is
what Internal means.
"""

from __future__ import annotations

import frappe

RETIRED = ("Customs", "Finance", "Other")


def execute() -> None:
	if not frappe.db.table_exists("Shipment Update"):
		return

	placeholders = ", ".join(["%s"] * len(RETIRED))
	moved = frappe.db.sql(
		f"""
		UPDATE `tabShipment Update`
		SET update_source = 'Internal'
		WHERE update_source IN ({placeholders})
		""",
		RETIRED,
	)
	if moved:
		frappe.db.commit()
	frappe.clear_cache(doctype="Shipment Update")
