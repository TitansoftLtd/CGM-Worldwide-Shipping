"""Wire KPA invoice tasks into application + finance workflow (existing sites)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_SEA_WORKFLOW_TASK_GATES,
	build_requirement_seed_rows,
)


def _requirement_rows(settings) -> list:
	return list(settings.get("custom_sea_clearance_task_requirements") or [])


def _has_kpa_application(rows: list) -> bool:
	return any(r.requirement_type == "KPA Application" for r in rows)


def _upgrade_requirements(settings) -> bool:
	rows = _requirement_rows(settings)
	if not rows:
		for row in build_requirement_seed_rows():
			settings.append("custom_sea_clearance_task_requirements", row)
		return True
	if _has_kpa_application(rows):
		return False

	old_kpa_finance = any(
		int(r.sequence_no or 0) == 20
		and r.requirement_type == "Finance Payment"
		and (r.value or "").strip() in ("Standard", "")
		for r in rows
	)
	if not old_kpa_finance:
		return False

	settings.set("custom_sea_clearance_task_requirements", [])
	for row in build_requirement_seed_rows():
		settings.append("custom_sea_clearance_task_requirements", row)
	return True


def _upgrade_gates(settings) -> bool:
	rows = list(settings.get("custom_sea_workflow_task_gates") or [])
	if not rows:
		for row in DEFAULT_SEA_WORKFLOW_TASK_GATES:
			settings.append("custom_sea_workflow_task_gates", row)
		return True

	kpa_paid = next(
		(r for r in rows if (r.shipment_workflow_state or "").strip() == "KPA Paid"),
		None,
	)
	if kpa_paid and (kpa_paid.gate_rule or "").strip() == "KPA Finance Complete":
		return False

	settings.set("custom_sea_workflow_task_gates", [])
	for row in DEFAULT_SEA_WORKFLOW_TASK_GATES:
		settings.append("custom_sea_workflow_task_gates", row)
	return True


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	changed = False

	if meta.has_field("custom_sea_clearance_task_requirements"):
		changed = _upgrade_requirements(settings) or changed
	if meta.has_field("custom_sea_workflow_task_gates"):
		changed = _upgrade_gates(settings) or changed

	if changed:
		settings.save(ignore_permissions=True)
	frappe.db.commit()
