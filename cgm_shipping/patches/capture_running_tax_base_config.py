"""Capture Customs Tax Type config before Running Tax Base schema migration."""

from __future__ import annotations

import json
from pathlib import Path

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	parse_allowed_modes,
)

SNAPSHOT_NAME = "customs_tax_type_running_base_snapshot.json"

_CAPTURE_FIELDS = (
	"default_calculation_mode",
	"percentage_base",
	"include_in_duty_pool",
	"include_in_subsequent_tax_base",
	"add_to_cumulative_base",
	"exclude_from_bases_when_per_unit",
)


def _snapshot_path() -> Path:
	return Path(frappe.get_site_path("private", "files", SNAPSHOT_NAME))


def execute() -> None:
	if not frappe.db.exists("DocType", "Customs Tax Type"):
		return

	columns = set(frappe.db.get_table_columns("Customs Tax Type") or [])
	# Already on the target schema — nothing to capture for rename.
	if "include_in_subsequent_tax_base" in columns and "include_in_duty_pool" not in columns:
		return

	available = [f for f in _CAPTURE_FIELDS if f in columns]
	fields = ["name", *available]
	rows = frappe.get_all("Customs Tax Type", fields=fields)

	snapshot = []
	for row in rows:
		modes: list[str] = []
		if frappe.db.exists("DocType", "Customs Tax Allowed Mode"):
			modes = frappe.get_all(
				"Customs Tax Allowed Mode",
				filters={"parent": row.name, "parenttype": "Customs Tax Type"},
				pluck="calculation_mode",
				order_by="idx asc",
			)
		modes = list(parse_allowed_modes(modes))

		snapshot.append(
			{
				"name": row.name,
				"allowed_modes": modes,
				"default_calculation_mode": (row.get("default_calculation_mode") or "").strip(),
				"percentage_base": (row.get("percentage_base") or "").strip(),
				"include_in_duty_pool": frappe.utils.cint(row.get("include_in_duty_pool", 0)),
				"include_in_subsequent_tax_base": row.get("include_in_subsequent_tax_base"),
				"add_to_cumulative_base": frappe.utils.cint(row.get("add_to_cumulative_base", 1)),
				"exclude_from_bases_when_per_unit": frappe.utils.cint(
					row.get("exclude_from_bases_when_per_unit", 0)
				),
			}
		)

	path = _snapshot_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
