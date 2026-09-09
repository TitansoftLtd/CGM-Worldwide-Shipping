"""Rebuild Customs Tax Type config after schema migration to Table MultiSelect.

Idempotent: skips rows that already have allowed modes and percentage_base.
Compatible with the Running Tax Base field model.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	CALC_MODE_FIXED_AMOUNT,
	CALC_MODE_PERCENTAGE,
	CALC_MODE_PER_UNIT,
	PERCENTAGE_BASE_CUSTOMS_VALUE,
	PERCENTAGE_BASE_RUNNING_TAX_BASE,
	normalize_percentage_base,
	parse_allowed_modes,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_type_seed_data import (
	CUSTOMS_CALCULATION_MODES,
	CUSTOMS_TAX_TYPES,
)

SNAPSHOT_NAME = "customs_tax_type_config_snapshot.json"


def _snapshot_path() -> Path:
	return Path(frappe.get_site_path("private", "files", SNAPSHOT_NAME))


def _ensure_calculation_modes() -> None:
	if not frappe.db.exists("DocType", "Customs Calculation Mode"):
		return
	for row in CUSTOMS_CALCULATION_MODES:
		name = row["mode_name"]
		if frappe.db.exists("Customs Calculation Mode", name):
			continue
		frappe.get_doc({"doctype": "Customs Calculation Mode", **row}).insert(
			ignore_permissions=True
		)


def _set_allowed_modes(tax_type: str, modes: list[str]) -> None:
	frappe.db.delete(
		"Customs Tax Allowed Mode",
		{"parent": tax_type, "parenttype": "Customs Tax Type"},
	)
	for idx, mode in enumerate(modes, start=1):
		if not mode or not frappe.db.exists("Customs Calculation Mode", mode):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Customs Tax Allowed Mode",
				"parent": tax_type,
				"parenttype": "Customs Tax Type",
				"parentfield": "allowed_calculation_modes",
				"idx": idx,
				"calculation_mode": mode,
			}
		)
		doc.db_insert()


def _include_from_values(values: dict) -> int:
	if "include_in_subsequent_tax_base" in values:
		return frappe.utils.cint(values.get("include_in_subsequent_tax_base", 0))
	if values.get("exclude_from_bases_when_per_unit"):
		return 0
	return frappe.utils.cint(values.get("add_to_cumulative_base", 0)) or frappe.utils.cint(
		values.get("include_in_duty_pool", 0)
	)


def _apply_row(name: str, values: dict) -> None:
	if not frappe.db.exists("Customs Tax Type", name):
		return

	modes = values.get("allowed_modes") or []
	if isinstance(modes, str):
		modes = list(parse_allowed_modes(modes))

	default_mode = (values.get("default_calculation_mode") or "").strip()
	if default_mode and default_mode not in modes and modes:
		default_mode = modes[0]
	if not default_mode and modes:
		default_mode = modes[0]

	update = {
		"default_calculation_mode": default_mode or CALC_MODE_PERCENTAGE,
		"percentage_base": normalize_percentage_base(
			values.get("percentage_base") or PERCENTAGE_BASE_CUSTOMS_VALUE
		),
	}
	meta = frappe.get_meta("Customs Tax Type")
	if meta.has_field("include_in_subsequent_tax_base"):
		update["include_in_subsequent_tax_base"] = _include_from_values(values)
	elif meta.has_field("include_in_duty_pool"):
		update["include_in_duty_pool"] = frappe.utils.cint(values.get("include_in_duty_pool", 0))
		if meta.has_field("add_to_cumulative_base"):
			update["add_to_cumulative_base"] = frappe.utils.cint(
				values.get("add_to_cumulative_base", 1)
			)
		if meta.has_field("exclude_from_bases_when_per_unit"):
			update["exclude_from_bases_when_per_unit"] = frappe.utils.cint(
				values.get("exclude_from_bases_when_per_unit", 0)
			)

	frappe.db.set_value("Customs Tax Type", name, update, update_modified=False)
	_set_allowed_modes(name, list(modes) if modes else [CALC_MODE_PERCENTAGE])


def _seed_row_to_migration(row: dict) -> dict:
	modes = [
		(item.get("calculation_mode") if isinstance(item, dict) else item)
		for item in (row.get("allowed_calculation_modes") or [])
	]
	result = {
		"allowed_modes": [m for m in modes if m],
		"default_calculation_mode": row["default_calculation_mode"],
		"percentage_base": row["percentage_base"],
	}
	if "include_in_subsequent_tax_base" in row:
		result["include_in_subsequent_tax_base"] = row["include_in_subsequent_tax_base"]
	else:
		result["include_in_duty_pool"] = row.get("include_in_duty_pool", 0)
		result["add_to_cumulative_base"] = row.get("add_to_cumulative_base", 1)
		result["exclude_from_bases_when_per_unit"] = row.get(
			"exclude_from_bases_when_per_unit", 0
		)
	return result


def _legacy_columns_to_values(name: str) -> dict | None:
	"""Best-effort read if snapshot missing but old columns still exist briefly."""
	meta = frappe.get_meta("Customs Tax Type")
	if not meta.has_field("is_stacking"):
		return None

	row = frappe.db.get_value(
		"Customs Tax Type",
		name,
		[
			"allowed_calculation_modes",
			"default_calculation_mode",
			"is_stacking",
			"is_excise",
			"affects_import_duty",
			"feeds_running_base",
			"per_unit_skips_running_base",
		],
		as_dict=True,
	)
	if not row:
		return None

	if frappe.utils.cint(row.is_excise):
		percentage_base = PERCENTAGE_BASE_RUNNING_TAX_BASE
	elif frappe.utils.cint(row.is_stacking):
		percentage_base = PERCENTAGE_BASE_RUNNING_TAX_BASE
	else:
		percentage_base = PERCENTAGE_BASE_CUSTOMS_VALUE

	modes = list(parse_allowed_modes(row.allowed_calculation_modes))
	return {
		"allowed_modes": modes,
		"default_calculation_mode": (row.default_calculation_mode or "").strip(),
		"percentage_base": percentage_base,
		"include_in_duty_pool": frappe.utils.cint(row.affects_import_duty),
		"add_to_cumulative_base": frappe.utils.cint(row.feeds_running_base),
		"exclude_from_bases_when_per_unit": frappe.utils.cint(row.per_unit_skips_running_base),
		"include_in_subsequent_tax_base": (
			0
			if frappe.utils.cint(row.per_unit_skips_running_base)
			else frappe.utils.cint(row.feeds_running_base)
			or frappe.utils.cint(row.affects_import_duty)
		),
	}


def execute() -> None:
	if not frappe.db.exists("DocType", "Customs Tax Type"):
		return
	if not frappe.get_meta("Customs Tax Type").has_field("percentage_base"):
		return

	_ensure_calculation_modes()

	snapshot: list[dict] = []
	path = _snapshot_path()
	if path.exists():
		try:
			snapshot = json.loads(path.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError):
			snapshot = []

	by_name = {row["name"]: row for row in snapshot if row.get("name")}
	seed_by_name = {row["tax_name"]: _seed_row_to_migration(row) for row in CUSTOMS_TAX_TYPES}

	for name in frappe.get_all("Customs Tax Type", pluck="name"):
		# Skip rows that already have child modes and new fields filled.
		existing_modes = frappe.get_all(
			"Customs Tax Allowed Mode",
			filters={"parent": name, "parenttype": "Customs Tax Type"},
			pluck="calculation_mode",
		)
		percentage_base = frappe.db.get_value("Customs Tax Type", name, "percentage_base")
		if existing_modes and percentage_base:
			# Still normalize legacy Select values if present.
			normalized = normalize_percentage_base(percentage_base)
			if normalized != percentage_base:
				frappe.db.set_value(
					"Customs Tax Type",
					name,
					"percentage_base",
					normalized,
					update_modified=False,
				)
			continue

		values = by_name.get(name) or _legacy_columns_to_values(name) or seed_by_name.get(name)
		if not values:
			values = {
				"allowed_modes": [CALC_MODE_PERCENTAGE],
				"default_calculation_mode": CALC_MODE_PERCENTAGE,
				"percentage_base": PERCENTAGE_BASE_CUSTOMS_VALUE,
				"include_in_subsequent_tax_base": 1,
			}
		_apply_row(name, values)

	# Ensure seeded calculation modes cover Fixed Amount / Per Unit even if unused.
	for mode in (CALC_MODE_PERCENTAGE, CALC_MODE_PER_UNIT, CALC_MODE_FIXED_AMOUNT):
		if not frappe.db.exists("Customs Calculation Mode", mode):
			frappe.get_doc(
				{"doctype": "Customs Calculation Mode", "mode_name": mode}
			).insert(ignore_permissions=True)

	if path.exists():
		try:
			path.unlink()
		except OSError:
			pass

	frappe.clear_cache(doctype="Customs Tax Type")
	frappe.db.commit()
