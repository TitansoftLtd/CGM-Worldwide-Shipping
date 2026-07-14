"""Migrate Customs Tax Type config to Running Tax Base model.

Maps:
- Cumulative Base / Customs Value + Duty Pool → Running Tax Base
- include_in_duty_pool (+ related flags) → include_in_subsequent_tax_base

Known seeded tax types are reapplied from CUSTOMS_TAX_TYPES so business rules
match the configuration-driven model.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	CALC_MODE_PERCENTAGE,
	PERCENTAGE_BASE_CUSTOMS_VALUE,
	normalize_percentage_base,
	parse_allowed_modes,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_type_seed_data import (
	CUSTOMS_TAX_TYPES,
)

SNAPSHOT_NAME = "customs_tax_type_running_base_snapshot.json"


def _snapshot_path() -> Path:
	return Path(frappe.get_site_path("private", "files", SNAPSHOT_NAME))


def _set_allowed_modes(tax_type: str, modes: list[str]) -> None:
	if not frappe.db.exists("DocType", "Customs Tax Allowed Mode"):
		return

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


def _seed_row_values(row: dict) -> dict:
	modes = [
		(item.get("calculation_mode") if isinstance(item, dict) else item)
		for item in (row.get("allowed_calculation_modes") or [])
	]
	return {
		"allowed_modes": [m for m in modes if m],
		"default_calculation_mode": row["default_calculation_mode"],
		"percentage_base": row["percentage_base"],
		"include_in_subsequent_tax_base": frappe.utils.cint(
			row.get("include_in_subsequent_tax_base", 0)
		),
	}


def _map_snapshot_row(row: dict) -> dict:
	"""Derive new-model values from a pre-migrate snapshot row."""
	if row.get("include_in_subsequent_tax_base") is not None:
		include = frappe.utils.cint(row["include_in_subsequent_tax_base"])
	elif row.get("exclude_from_bases_when_per_unit"):
		# Per-unit levies that previously skipped bases should not grow the RTB.
		include = 0
	else:
		# Prefer the cumulative-feed flag; fall back to duty-pool membership.
		include = frappe.utils.cint(row.get("add_to_cumulative_base", 0)) or frappe.utils.cint(
			row.get("include_in_duty_pool", 0)
		)

	modes = list(parse_allowed_modes(row.get("allowed_modes") or []))
	return {
		"allowed_modes": modes,
		"default_calculation_mode": (row.get("default_calculation_mode") or "").strip(),
		"percentage_base": normalize_percentage_base(row.get("percentage_base")),
		"include_in_subsequent_tax_base": include,
	}


def _apply_row(name: str, values: dict) -> None:
	if not frappe.db.exists("Customs Tax Type", name):
		return
	if not frappe.get_meta("Customs Tax Type").has_field("include_in_subsequent_tax_base"):
		return

	modes = values.get("allowed_modes") or []
	if isinstance(modes, str):
		modes = list(parse_allowed_modes(modes))

	default_mode = (values.get("default_calculation_mode") or "").strip()
	if default_mode and default_mode not in modes and modes:
		default_mode = modes[0]
	if not default_mode and modes:
		default_mode = modes[0]

	frappe.db.set_value(
		"Customs Tax Type",
		name,
		{
			"default_calculation_mode": default_mode or CALC_MODE_PERCENTAGE,
			"percentage_base": values.get("percentage_base") or PERCENTAGE_BASE_CUSTOMS_VALUE,
			"include_in_subsequent_tax_base": frappe.utils.cint(
				values.get("include_in_subsequent_tax_base", 0)
			),
		},
		update_modified=False,
	)
	if modes:
		_set_allowed_modes(name, list(modes))


def execute() -> None:
	if not frappe.db.exists("DocType", "Customs Tax Type"):
		return
	meta = frappe.get_meta("Customs Tax Type")
	if not meta.has_field("include_in_subsequent_tax_base"):
		return

	snapshot: list[dict] = []
	path = _snapshot_path()
	if path.exists():
		try:
			snapshot = json.loads(path.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError):
			snapshot = []

	by_name = {row["name"]: _map_snapshot_row(row) for row in snapshot if row.get("name")}
	seed_by_name = {row["tax_name"]: _seed_row_values(row) for row in CUSTOMS_TAX_TYPES}

	for name in frappe.get_all("Customs Tax Type", pluck="name"):
		# Seeded tax types get the canonical configuration-driven behaviour.
		if name in seed_by_name:
			_apply_row(name, seed_by_name[name])
			continue

		if name in by_name:
			_apply_row(name, by_name[name])
			continue

		# Custom types created after schema change — normalize percentage base only.
		current_base = frappe.db.get_value("Customs Tax Type", name, "percentage_base")
		normalized = normalize_percentage_base(current_base)
		if normalized != current_base:
			frappe.db.set_value(
				"Customs Tax Type",
				name,
				"percentage_base",
				normalized,
				update_modified=False,
			)

	if path.exists():
		try:
			path.unlink()
		except OSError:
			pass

	frappe.clear_cache(doctype="Customs Tax Type")
	frappe.db.commit()
