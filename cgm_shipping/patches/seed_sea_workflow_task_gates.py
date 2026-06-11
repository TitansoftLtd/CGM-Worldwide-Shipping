"""Seed CGM Shipping Settings: sea workflow task gates (when empty)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_SEA_WORKFLOW_TASK_GATES,
)


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("custom_sea_workflow_task_gates"):
		return
	if settings.get("custom_sea_workflow_task_gates"):
		return

	for row in DEFAULT_SEA_WORKFLOW_TASK_GATES:
		settings.append("custom_sea_workflow_task_gates", row)

	settings.save(ignore_permissions=True)
	frappe.db.commit()
