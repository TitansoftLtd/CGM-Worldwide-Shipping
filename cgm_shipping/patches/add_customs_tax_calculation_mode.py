"""Backfill calculation_mode on existing customs tax rows."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	default_mode_for_tax,
)


def execute():
	if not frappe.db.has_column("Customs Tax Component", "calculation_mode"):
		return

	for row in frappe.get_all(
		"Customs Tax Component",
		fields=["name", "tax_type", "calculation_mode"],
		filters={"parenttype": ["in", ["Quotation"]]},
	):
		if row.calculation_mode:
			continue
		mode = default_mode_for_tax(row.tax_type or "")
		frappe.db.set_value(
			"Customs Tax Component",
			row.name,
			"calculation_mode",
			mode,
			update_modified=False,
		)

	frappe.db.commit()
