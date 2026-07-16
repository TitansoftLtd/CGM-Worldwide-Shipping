"""Optional execute helper wrapping install seed of Customs Tax Types.

Not registered in patches.txt. Fresh installs use default_seed_data instead.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_type_seed_data import (
	CUSTOMS_CALCULATION_MODES,
	CUSTOMS_TAX_TYPES,
	DEFAULT_CUSTOMS_TAX_RATES,
)


def execute():
	_ensure_customs_calculation_modes()
	_ensure_customs_tax_types()
	_seed_default_customs_tax_rates()


def _ensure_customs_calculation_modes() -> None:
	if not frappe.db.exists("DocType", "Customs Calculation Mode"):
		return
	for row in CUSTOMS_CALCULATION_MODES:
		name = row["mode_name"]
		if frappe.db.exists("Customs Calculation Mode", name):
			continue
		frappe.get_doc({"doctype": "Customs Calculation Mode", **row}).insert(
			ignore_permissions=True
		)
	frappe.db.commit()


def _ensure_customs_tax_types() -> None:
	if not frappe.db.exists("DocType", "Customs Tax Type"):
		return

	for row in CUSTOMS_TAX_TYPES:
		name = row["tax_name"]
		if frappe.db.exists("Customs Tax Type", name):
			continue
		frappe.get_doc({"doctype": "Customs Tax Type", **row}).insert(ignore_permissions=True)

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
