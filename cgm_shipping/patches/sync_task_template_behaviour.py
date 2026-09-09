"""Ensure Task Role / Payment Kind / Permit Stage on templates and open Tasks."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.clearance_charge_item import (
	ensure_payment_kinds,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
	ensure_task_behaviour_fields,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	backfill_open_task_behaviour_from_templates,
	seed_cgm_task_templates,
	sync_template_behaviour_fields,
)


def execute() -> None:
	ensure_payment_kinds()
	ensure_task_behaviour_fields()
	seed_cgm_task_templates()
	sync_template_behaviour_fields()
	backfill_open_task_behaviour_from_templates()
	frappe.clear_cache(doctype="Task")
	frappe.clear_cache(doctype="CGM Task Template")
