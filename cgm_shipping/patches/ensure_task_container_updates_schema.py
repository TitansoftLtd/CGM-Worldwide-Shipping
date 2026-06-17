"""Install Task Container Update child table and Task custom fields."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	ensure_container_tracking_settings_fields,
	ensure_task_container_update_fields,
)


def execute():
	if not frappe.db.exists("DocType", "Task Container Update"):
		return
	ensure_container_tracking_settings_fields()
	ensure_task_container_update_fields()
	frappe.clear_cache(doctype="Task")
	frappe.db.commit()
