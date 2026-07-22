"""Idempotent master-data seeds for fresh site installs."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_SEA_WORKFLOW_TASK_GATES,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_type_seed_data import (
	CUSTOMS_CALCULATION_MODES,
	CUSTOMS_TAX_TYPES,
	DEFAULT_CUSTOMS_TAX_RATES,
)


def seed_customs_calculation_modes() -> None:
	if not frappe.db.exists("DocType", "Customs Calculation Mode"):
		return

	for row in CUSTOMS_CALCULATION_MODES:
		name = row["mode_name"]
		if frappe.db.exists("Customs Calculation Mode", name):
			continue
		frappe.get_doc({"doctype": "Customs Calculation Mode", **row}).insert(
			ignore_permissions=True
		)


def seed_customs_tax_types() -> None:
	if not frappe.db.exists("DocType", "Customs Tax Type"):
		return

	seed_customs_calculation_modes()

	for row in CUSTOMS_TAX_TYPES:
		name = row["tax_name"]
		if frappe.db.exists("Customs Tax Type", name):
			# Do not overwrite live master data on re-seed.
			continue
		frappe.get_doc({"doctype": "Customs Tax Type", **row}).insert(ignore_permissions=True)


def seed_default_customs_tax_rates() -> None:
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


def seed_cgm_shipping_settings() -> None:
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
		reseed_sea_clearance_task_requirements,
	)

	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	changed = False

	if meta.has_field("custom_sea_clearance_task_requirements"):
		changed = reseed_sea_clearance_task_requirements(settings) or changed

	if meta.has_field("custom_sea_workflow_task_gates") and not settings.get(
		"custom_sea_workflow_task_gates"
	):
		for row in DEFAULT_SEA_WORKFLOW_TASK_GATES:
			settings.append("custom_sea_workflow_task_gates", row)
		changed = True

	if meta.has_field("sea_import_template") and not settings.get("sea_import_template"):
		if frappe.db.exists("CGM Task Template", "Sea Import Workflow"):
			settings.sea_import_template = "Sea Import Workflow"
			changed = True

	if changed:
		settings.save(ignore_permissions=True)
		frappe.clear_cache()



def seed_all_defaults() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		seed_task_workflow_masters,
	)

	seed_customs_tax_types()
	seed_default_customs_tax_rates()
	seed_cgm_shipping_settings()
	seed_task_workflow_masters()
	frappe.db.commit()
