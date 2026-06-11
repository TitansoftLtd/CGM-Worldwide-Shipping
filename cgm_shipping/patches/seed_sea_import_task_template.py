"""Seed CGM Shipping Settings: 24-step sea import task template (when empty)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_SEA_IMPORT_TASK_TEMPLATE,
)


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("custom_sea_import_task_template"):
		return
	if settings.get("custom_sea_import_task_template"):
		return

	for row in DEFAULT_SEA_IMPORT_TASK_TEMPLATE:
		settings.append("custom_sea_import_task_template", row)

	settings.save(ignore_permissions=True)
	frappe.db.commit()
