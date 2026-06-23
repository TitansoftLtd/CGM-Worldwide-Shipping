"""Set MSS Levy to Per Weight calculation type."""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.exists("Customs Tax Type", "MSS Levy"):
		return

	frappe.db.set_value(
		"Customs Tax Type",
		"MSS Levy",
		"calculation_type",
		"Per Weight",
		update_modified=False,
	)
	frappe.db.commit()
