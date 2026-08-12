"""Stamp Required Document Types from templates onto open Tasks (e.g. IDF CERT on UCR)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
	ensure_task_behaviour_fields,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	backfill_open_task_behaviour_from_templates,
	sync_template_behaviour_fields,
)


def execute() -> None:
	frappe.reload_doc(
		"cgm_worldwide_shipping",
		"doctype",
		"cgm_task_template_item",
		force=True,
	)
	ensure_task_behaviour_fields()
	sync_template_behaviour_fields()
	backfill_open_task_behaviour_from_templates()
	frappe.clear_cache(doctype="CGM Task Template Item")
	frappe.clear_cache(doctype="CGM Task Template")
	frappe.clear_cache(doctype="Task")
