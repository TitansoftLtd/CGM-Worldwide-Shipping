"""Backfill calculation_mode on existing customs tax rows.

Ensures Customs Tax Type config exists before resolving defaults (migration-safe).
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	CALC_MODE_PERCENTAGE,
	default_mode_for_tax,
	parse_allowed_modes,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_type_seed_data import (
	CUSTOMS_TAX_TYPES,
)

_SEED_BY_NAME = {row["tax_name"]: row for row in CUSTOMS_TAX_TYPES}


def _ensure_tax_type_config() -> None:
	"""Fill blank Customs Tax Type config so strict validation can run (legacy schema only)."""
	if not frappe.db.exists("DocType", "Customs Tax Type"):
		return
	if not frappe.get_meta("Customs Tax Type").has_field("allowed_calculation_modes"):
		return

	df = frappe.get_meta("Customs Tax Type").get_field("allowed_calculation_modes")
	if df and df.fieldtype == "Table MultiSelect":
		return

	for name, values in _SEED_BY_NAME.items():
		if not frappe.db.exists("Customs Tax Type", name):
			continue
		existing = frappe.db.get_value(
			"Customs Tax Type", name, "allowed_calculation_modes"
		)
		if existing and str(existing).strip():
			continue
		meta = frappe.get_meta("Customs Tax Type")
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
			if key in values and meta.has_field(key) and isinstance(values[key], (str, int))
		}
		if update:
			frappe.db.set_value("Customs Tax Type", name, update, update_modified=False)

	frappe.db.commit()


def _default_mode_for_backfill(tax_type: str) -> str:
	"""Resolve default mode without raising during one-time row backfill."""
	if not tax_type:
		return CALC_MODE_PERCENTAGE

	if frappe.db.exists("Customs Tax Type", tax_type):
		try:
			return default_mode_for_tax(tax_type)
		except frappe.ValidationError:
			pass

		meta = frappe.get_meta("Customs Tax Type")
		if meta.has_field("allowed_calculation_modes"):
			df = meta.get_field("allowed_calculation_modes")
			if df and df.fieldtype == "Table MultiSelect":
				modes = frappe.get_all(
					"Customs Tax Allowed Mode",
					filters={"parent": tax_type, "parenttype": "Customs Tax Type"},
					pluck="calculation_mode",
				)
				default_mode = (
					frappe.db.get_value(
						"Customs Tax Type", tax_type, "default_calculation_mode"
					)
					or ""
				).strip()
				if modes and default_mode in modes:
					return default_mode
				if modes:
					return modes[0]
			else:
				values = frappe.db.get_value(
					"Customs Tax Type",
					tax_type,
					["allowed_calculation_modes", "default_calculation_mode"],
					as_dict=True,
				)
				if values:
					modes = parse_allowed_modes(values.get("allowed_calculation_modes"))
					default_mode = (values.get("default_calculation_mode") or "").strip()
					if modes and default_mode in modes:
						return default_mode
					if modes:
						return modes[0]

	seed = _SEED_BY_NAME.get(tax_type)
	if seed:
		return seed["default_calculation_mode"]

	return CALC_MODE_PERCENTAGE


def execute():
	if not frappe.db.has_column("Customs Tax Component", "calculation_mode"):
		return

	_ensure_tax_type_config()

	for row in frappe.get_all(
		"Customs Tax Component",
		fields=["name", "tax_type", "calculation_mode"],
		filters={"parenttype": ["in", ["Quotation"]]},
	):
		if row.calculation_mode:
			continue
		mode = _default_mode_for_backfill(row.tax_type or "")
		frappe.db.set_value(
			"Customs Tax Component",
			row.name,
			"calculation_mode",
			mode,
			update_modified=False,
		)

	frappe.db.commit()
