"""Container Tracker as source of truth; Supplier tier tables; slim Project Container child."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	ensure_project_container_tracking_fields,
	ensure_task_container_fields,
)


def execute():
	ensure_project_container_tracking_fields()
	ensure_task_container_fields()
	frappe.clear_cache(doctype="Container")
	frappe.clear_cache(doctype="Container Tracker")
	frappe.clear_cache(doctype="Supplier")
	frappe.db.commit()
