"""Seed CGM Shipping Settings: sea clearance task requirements (when empty)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	build_requirement_seed_rows,
)


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("custom_sea_clearance_task_requirements"):
		return
	if settings.get("custom_sea_clearance_task_requirements"):
		return

	for row in build_requirement_seed_rows():
		settings.append("custom_sea_clearance_task_requirements", row)

	settings.save(ignore_permissions=True)
	frappe.db.commit()
