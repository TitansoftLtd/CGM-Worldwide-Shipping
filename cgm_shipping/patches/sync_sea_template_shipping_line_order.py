"""Sync sea import template so Shipping Line Invoice comes before Create Entry.

Also updates legacy CGM Shipping Settings container task sequences and ensures
cargo type fields exist. Idempotent — safe to re-run on migrate.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CONTAINER_TASK_SEQ_DEFAULTS,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	ensure_cargo_type_fields,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_SEA_IMPORT_TASK_TEMPLATE,
	DEFAULT_SEA_WORKFLOW_TASK_GATES,
	build_requirement_seed_rows,
)

SHIPPING_LINE_APPLICATION_SUBJECT = "Attach Shipping Line Invoice"
CREATE_ENTRY_PREFIX = "Create Entry"

# Known prior DocType / installer defaults that should move to CONTAINER_TASK_SEQ_DEFAULTS.
_OLD_CONTAINER_TASK_SEQ_DEFAULTS: dict[str, tuple[int, ...]] = {
	"custom_vessel_arrival_task_seq": (11,),
	"custom_field_clearance_task_seq": (16, 18),
	"custom_kpa_paid_task_seq": (18, 20),
	"custom_book_trucks_task_seq": (19, 21),
	"custom_gate_out_task_seq": (20, 22),
	"custom_monitor_delivery_task_seq": (21, 23),
	"custom_offload_task_seq": (22, 24),
	"custom_empty_return_task_seq": (23, 25),
	"custom_interchange_task_seq": (24, 26),
}


def _template_has_entry_before_shipping_line(rows: list) -> bool:
	subjects = [(row.task_subject or "").strip() for row in rows]
	entry_idx = next(
		(i for i, subject in enumerate(subjects) if subject.startswith(CREATE_ENTRY_PREFIX)),
		None,
	)
	sl_idx = next(
		(i for i, subject in enumerate(subjects) if subject == SHIPPING_LINE_APPLICATION_SUBJECT),
		None,
	)
	if entry_idx is None or sl_idx is None:
		return False
	return entry_idx < sl_idx


def _reseed_settings_from_defaults(settings) -> bool:
	"""Replace template / requirements / gates only when Entry still precedes SL Invoice."""
	meta = frappe.get_meta("CGM Shipping Settings")
	changed = False

	if meta.has_field("custom_sea_import_task_template"):
		rows = list(settings.get("custom_sea_import_task_template") or [])
		if not rows or _template_has_entry_before_shipping_line(rows):
			settings.set("custom_sea_import_task_template", [])
			for row in DEFAULT_SEA_IMPORT_TASK_TEMPLATE:
				settings.append("custom_sea_import_task_template", row)
			changed = True

			if meta.has_field("custom_sea_clearance_task_requirements"):
				settings.set("custom_sea_clearance_task_requirements", [])
				for row in build_requirement_seed_rows():
					settings.append("custom_sea_clearance_task_requirements", row)

			if meta.has_field("custom_sea_workflow_task_gates"):
				settings.set("custom_sea_workflow_task_gates", [])
				for row in DEFAULT_SEA_WORKFLOW_TASK_GATES:
					settings.append("custom_sea_workflow_task_gates", row)

	return changed


def _sync_container_task_seq_defaults(settings) -> bool:
	meta = frappe.get_meta("CGM Shipping Settings")
	changed = False
	for fieldname, old_values in _OLD_CONTAINER_TASK_SEQ_DEFAULTS.items():
		if not meta.has_field(fieldname):
			continue
		new_value = CONTAINER_TASK_SEQ_DEFAULTS.get(fieldname)
		if new_value is None:
			continue
		current = int(settings.get(fieldname) or 0)
		if current in old_values and current != new_value:
			settings.set(fieldname, new_value)
			changed = True
	return changed


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		ensure_cargo_type_fields()
		frappe.clear_cache()
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	changed = False
	changed = _reseed_settings_from_defaults(settings) or changed
	changed = _sync_container_task_seq_defaults(settings) or changed
	if changed:
		settings.save(ignore_permissions=True)

	ensure_cargo_type_fields()
	frappe.clear_cache()
