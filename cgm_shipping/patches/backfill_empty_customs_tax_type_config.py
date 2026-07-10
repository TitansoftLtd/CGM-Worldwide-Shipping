"""One-time backfill of empty Customs Tax Type calculation config.

Only fills rows where allowed_calculation_modes is blank. Does not overwrite
admin-configured masters. Recorded in Patch Log so it does not re-run.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_type_seed_data import (
	CUSTOMS_TAX_TYPES,
)


def execute() -> None:
	if not frappe.db.exists("DocType", "Customs Tax Type"):
		return
	if not frappe.get_meta("Customs Tax Type").has_field("allowed_calculation_modes"):
		return

	by_name = {row["tax_name"]: row for row in CUSTOMS_TAX_TYPES}
	for name, values in by_name.items():
		if not frappe.db.exists("Customs Tax Type", name):
			continue
		existing = frappe.db.get_value(
			"Customs Tax Type", name, "allowed_calculation_modes"
		)
		if existing and str(existing).strip():
			continue
		update = {
			key: values[key]
			for key in (
				"allowed_calculation_modes",
				"default_calculation_mode",
				"is_stacking",
				"is_excise",
				"affects_import_duty",
				"feeds_running_base",
				"per_unit_skips_running_base",
			)
			if key in values
		}
		frappe.db.set_value("Customs Tax Type", name, update, update_modified=False)

	frappe.db.commit()
