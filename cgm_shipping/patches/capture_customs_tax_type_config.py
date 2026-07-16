"""Capture Customs Tax Type config before the DocType schema changes.

Stores a JSON snapshot under the site so the post-migrate patch can rebuild
Allowed Calculation Modes (Table MultiSelect) and the new behaviour fields.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	PERCENTAGE_BASE_CUSTOMS_VALUE,
	PERCENTAGE_BASE_RUNNING_TAX_BASE,
	parse_allowed_modes,
)

SNAPSHOT_NAME = "customs_tax_type_config_snapshot.json"

_LEGACY_FIELDS = (
	"allowed_calculation_modes",
	"default_calculation_mode",
	"is_stacking",
	"is_excise",
	"affects_import_duty",
	"feeds_running_base",
	"per_unit_skips_running_base",
)


def _snapshot_path() -> Path:
	return Path(frappe.get_site_path("private", "files", SNAPSHOT_NAME))


def _percentage_base_from_legacy(row: dict) -> str:
	if frappe.utils.cint(row.get("is_excise")):
		return PERCENTAGE_BASE_RUNNING_TAX_BASE
	if frappe.utils.cint(row.get("is_stacking")):
		return PERCENTAGE_BASE_RUNNING_TAX_BASE
	return PERCENTAGE_BASE_CUSTOMS_VALUE


def execute() -> None:
	if not frappe.db.exists("DocType", "Customs Tax Type"):
		return

	# Prefer DB columns over meta — pre_model_sync still has the old table.
	available = [f for f in _LEGACY_FIELDS if frappe.db.has_column("Customs Tax Type", f)]
	if "allowed_calculation_modes" not in available:
		return
	if "is_stacking" not in available and "percentage_base" in (
		frappe.db.get_table_columns("Customs Tax Type") or []
	):
		# Already on the new schema.
		return

	# Skip if the column is no longer a free-text field (already Table MultiSelect).
	# Table MultiSelect still has a parent column, but child rows are the source of truth.
	if frappe.db.exists("DocType", "Customs Tax Allowed Mode"):
		# Child doctype already present from a previous partial migrate — still capture
		# legacy text if the Small Text-style values remain on the parent.
		pass

	fields = ["name", *available]
	rows = frappe.get_all("Customs Tax Type", fields=fields)

	snapshot = []
	for row in rows:
		modes = list(parse_allowed_modes(row.get("allowed_calculation_modes")))
		# If modes already live in the child table, prefer those.
		if frappe.db.exists("DocType", "Customs Tax Allowed Mode"):
			child_modes = frappe.get_all(
				"Customs Tax Allowed Mode",
				filters={"parent": row.name, "parenttype": "Customs Tax Type"},
				pluck="calculation_mode",
				order_by="idx asc",
			)
			if child_modes:
				modes = list(parse_allowed_modes(child_modes))

		snapshot.append(
			{
				"name": row.name,
				"allowed_modes": modes,
				"default_calculation_mode": (row.get("default_calculation_mode") or "").strip(),
				"percentage_base": _percentage_base_from_legacy(row),
				"include_in_duty_pool": frappe.utils.cint(row.get("affects_import_duty", 1)),
				"add_to_cumulative_base": frappe.utils.cint(row.get("feeds_running_base", 1)),
				"exclude_from_bases_when_per_unit": frappe.utils.cint(
					row.get("per_unit_skips_running_base", 0)
				),
			}
		)

	path = _snapshot_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
