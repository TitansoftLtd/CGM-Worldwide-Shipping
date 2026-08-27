"""Show Number of Packages / Package Type from CGM Shipping Settings.

Visibility is generated from CGM Shipping Settings → Package field visibility.
Placement beside weight and AWB backfill stay in this patch.
"""

from __future__ import annotations

import json

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.package_field_visibility import (
	apply_package_field_depends_on,
	seed_package_visibility_defaults,
)


def execute():
	seed_package_visibility_defaults()
	apply_package_field_depends_on()
	_place_opportunity_packages_beside_weight()
	_backfill_packages_from_awb()
	frappe.clear_cache(doctype="Opportunity")
	frappe.clear_cache(doctype="Project")


def _set_depends_on(fieldname: str, depends_on: str) -> None:
	if not frappe.db.exists("Custom Field", fieldname):
		return
	frappe.db.set_value(
		"Custom Field",
		fieldname,
		{
			"depends_on": depends_on,
			"hidden": 0,
			"read_only_depends_on": "",
		},
		update_modified=False,
	)


def _place_opportunity_packages_beside_weight() -> None:
	name = "Opportunity-main-field_order"
	if not frappe.db.exists("Property Setter", name):
		return
	raw = frappe.db.get_value("Property Setter", name, "value") or ""
	try:
		order = json.loads(raw)
	except (TypeError, ValueError):
		return
	if not isinstance(order, list):
		return

	for fieldname in ("custom_number_of_packages", "custom_package_type"):
		if fieldname in order:
			order.remove(fieldname)

	anchor = "custom_gross_weight"
	if anchor not in order:
		return
	idx = order.index(anchor) + 1
	order[idx:idx] = ["custom_number_of_packages", "custom_package_type"]
	frappe.db.set_value("Property Setter", name, "value", json.dumps(order), update_modified=False)


def _backfill_packages_from_awb() -> None:
	if not frappe.db.has_column("Opportunity", "custom_air_waybill"):
		return
	rows = frappe.db.sql(
		"""
		SELECT name, custom_air_waybill
		FROM `tabOpportunity`
		WHERE ifnull(custom_air_waybill, '') != ''
			AND ifnull(custom_number_of_packages, '') = ''
		""",
		as_dict=True,
	)
	for row in rows:
		awb = row.custom_air_waybill
		if not frappe.db.exists("Air Waybill", awb):
			continue
		pkgs, ptype = frappe.db.get_value(
			"Air Waybill", awb, ["number_of_packages", "package_type"]
		) or (None, None)
		values = {}
		if pkgs not in (None, "", 0, "0"):
			values["custom_number_of_packages"] = str(pkgs).strip()
		if ptype not in (None, ""):
			values["custom_package_type"] = ptype
		if values:
			frappe.db.set_value("Opportunity", row.name, values, update_modified=False)
