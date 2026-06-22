"""Seed Customs Tax Type master records and default rates in CGM Shipping Settings."""

from __future__ import annotations

import frappe

CUSTOMS_TAX_TYPES: list[dict[str, str]] = [
	{"tax_name": "Duty", "calculation_type": "Percentage"},
	{"tax_name": "VAT", "calculation_type": "Percentage"},
	{"tax_name": "IDF", "calculation_type": "Percentage"},
	{"tax_name": "RDL", "calculation_type": "Percentage"},
	{"tax_name": "Excise Duty", "calculation_type": "Percentage"},
	{"tax_name": "MSS Levy", "calculation_type": "Per Weight"},
]

DEFAULT_CUSTOMS_TAX_RATES: dict[str, float] = {
	"VAT": 16,
	"IDF": 2.5,
	"RDL": 2,
}


def execute():
	_ensure_customs_tax_types()
	_seed_default_customs_tax_rates()


def _ensure_customs_tax_types() -> None:
	if not frappe.db.exists("DocType", "Customs Tax Type"):
		return

	for row in CUSTOMS_TAX_TYPES:
		name = row["tax_name"]
		if frappe.db.exists("Customs Tax Type", name):
			frappe.db.set_value(
				"Customs Tax Type",
				name,
				"calculation_type",
				row["calculation_type"],
				update_modified=False,
			)
			continue

		doc = frappe.get_doc({"doctype": "Customs Tax Type", **row})
		doc.insert(ignore_permissions=True)

	frappe.db.commit()


def _seed_default_customs_tax_rates() -> None:
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("custom_default_customs_taxes"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	if settings.get("custom_default_customs_taxes"):
		return

	for tax_type, default_rate in DEFAULT_CUSTOMS_TAX_RATES.items():
		if not frappe.db.exists("Customs Tax Type", tax_type):
			continue
		settings.append(
			"custom_default_customs_taxes",
			{"tax_type": tax_type, "default_rate": default_rate},
		)

	settings.save(ignore_permissions=True)
	frappe.db.commit()
