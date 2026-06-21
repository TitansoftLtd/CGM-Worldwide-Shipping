"""Upgrade CGM Shipping Settings for Entry Slip finance workflow (existing sites)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_ENTRY_APPLICATION_SEQS,
	DEFAULT_FINANCE_KIND_BY_SEQ,
	DEFAULT_SEA_IMPORT_TASK_TEMPLATE,
	DEFAULT_SEA_WORKFLOW_TASK_GATES,
	build_requirement_seed_rows,
)


def _template_has_entry_slip_task(rows: list) -> bool:
	return any(
		(row.task_subject or "").strip() == "Finance Pays Entry Slip" for row in rows
	)


def _upgrade_task_template(settings) -> bool:
	rows = list(settings.get("custom_sea_import_task_template") or [])
	if not rows:
		for row in DEFAULT_SEA_IMPORT_TASK_TEMPLATE:
			settings.append("custom_sea_import_task_template", row)
		return True
	if _template_has_entry_slip_task(rows):
		return False

	subjects = [(row.task_subject or "").strip() for row in rows]
	if "Confirm Entry Payment (Client/CGM)" not in subjects:
		return False

	new_rows: list[dict] = []
	for row in rows:
		subject = (row.task_subject or "").strip()
		if subject == "Confirm Entry Payment (Client/CGM)":
			continue
		new_rows.append(
			{
				"task_subject": row.task_subject,
				"department": row.department,
			}
		)
		if subject == "Create Entry (after vessel arrival confirmation)":
			new_rows.append(
				{
					"task_subject": "Finance Pays Entry Slip",
					"department": "Finance",
				}
			)

	settings.set("custom_sea_import_task_template", [])
	for row in new_rows:
		settings.append("custom_sea_import_task_template", row)
	return True


def _requirement_rows(settings) -> list:
	return list(settings.get("custom_sea_clearance_task_requirements") or [])


def _has_entry_application(rows: list) -> bool:
	return any(r.requirement_type == "Entry Application" for r in rows)


def _upgrade_requirements(settings) -> bool:
	rows = _requirement_rows(settings)
	if not rows:
		for row in build_requirement_seed_rows():
			settings.append("custom_sea_clearance_task_requirements", row)
		return True
	if _has_entry_application(rows):
		return False

	# Rebuild from defaults when the old Confirm Entry Payment pattern is present.
	old_finance_14 = any(
		int(r.sequence_no or 0) == 14
		and r.requirement_type == "Finance Payment"
		for r in rows
	)
	if not old_finance_14:
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

	entry_paid = next(
		(r for r in rows if (r.shipment_workflow_state or "").strip() == "Entry Paid"),
		None,
	)
	if entry_paid and (entry_paid.gate_rule or "") == "Entry Finance Complete":
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

	if meta.has_field("custom_sea_import_task_template"):
		changed = _upgrade_task_template(settings) or changed
	if meta.has_field("custom_sea_clearance_task_requirements"):
		changed = _upgrade_requirements(settings) or changed
	if meta.has_field("custom_sea_workflow_task_gates"):
		changed = _upgrade_gates(settings) or changed

	if changed:
		settings.save(ignore_permissions=True)
		frappe.db.commit()
