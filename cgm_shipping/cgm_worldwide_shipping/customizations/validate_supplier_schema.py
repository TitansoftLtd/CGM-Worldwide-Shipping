"""Validate Supplier shipping-line child table schema (bench execute)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.shipping_line_rates import (
	DEMURRAGE_TIERS_FIELD,
	FREE_DAYS_RULES_FIELD,
	SUPPLIER_CHILD_TABLE_FIELDS,
	get_supplier_child_rows,
	supplier_has_child_table_field,
)


def validate_supplier_shipping_line_schema(supplier_name: str) -> dict:
	"""Return schema status and child row counts for a Supplier."""
	result = {
		"supplier": supplier_name,
		"exists": bool(supplier_name and frappe.db.exists("Supplier", supplier_name)),
		"child_doctypes": {},
		"fields": {},
		"free_days_rules": [],
		"demurrage_tiers": [],
	}
	for doctype in (
		"Shipping Line Free Days Rule",
		"Shipping Line Demurrage Tier",
	):
		result["child_doctypes"][doctype] = frappe.db.exists("DocType", doctype)

	if not result["exists"]:
		return result

	for fieldname in SUPPLIER_CHILD_TABLE_FIELDS:
		result["fields"][fieldname] = supplier_has_child_table_field(fieldname)

	result["free_days_rules"] = get_supplier_child_rows(
		supplier_name, FREE_DAYS_RULES_FIELD
	)
	result["demurrage_tiers"] = get_supplier_child_rows(
		supplier_name, DEMURRAGE_TIERS_FIELD
	)
	return result


def run(supplier_name: str = "MAERSK") -> None:
	"""bench execute cgm_shipping.cgm_worldwide_shipping.customizations.validate_supplier_schema.run"""
	data = validate_supplier_shipping_line_schema(supplier_name)
	print("CHILD DOCTYPES:", data["child_doctypes"])
	print("SUPPLIER SCHEMA:", data["fields"])
	print("FREE DAYS RULES:", data["free_days_rules"])
	print("DEMURRAGE TIERS:", data["demurrage_tiers"])
	if not all(data["child_doctypes"].values()):
		print("FIX: run bench migrate (child doctypes missing)")
	elif not all(data["fields"].values()):
		print("FIX: run bench execute cgm_shipping.install.run")


@frappe.whitelist()
def validate_supplier_shipping_line_schema_api(supplier_name: str) -> dict:
	frappe.only_for(("System Manager", "Operations Manager"))
	return validate_supplier_shipping_line_schema(supplier_name)
