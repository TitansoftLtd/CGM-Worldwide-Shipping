"""Insert Attach Shipping Line Invoice task and upgrade finance workflow (existing sites)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CONTAINER_TASK_SEQ_DEFAULTS,
	SEA_TASK_FLOW_KEY,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import resolve_department_name
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_SEA_IMPORT_TASK_TEMPLATE,
	DEFAULT_SEA_WORKFLOW_TASK_GATES,
	build_requirement_seed_rows,
)

SHIPPING_LINE_APPLICATION_SUBJECT = "Attach Shipping Line Invoice"
SHIPPING_LINE_FINANCE_SUBJECT = "Finance pays Shipping Line Charges"

CONTAINER_SEQ_FIELD_BUMPS = {
	"custom_field_clearance_task_seq": (16, 17),
	"custom_kpa_paid_task_seq": (18, 19),
	"custom_book_trucks_task_seq": (19, 20),
	"custom_gate_out_task_seq": (20, 21),
	"custom_monitor_delivery_task_seq": (21, 22),
	"custom_offload_task_seq": (22, 23),
	"custom_empty_return_task_seq": (23, 24),
	"custom_interchange_task_seq": (24, 25),
}


def _template_has_shipping_line_application(rows: list) -> bool:
	return any(
		(row.task_subject or "").strip() == SHIPPING_LINE_APPLICATION_SUBJECT for row in rows
	)


def _upgrade_task_template(settings) -> bool:
	rows = list(settings.get("custom_sea_import_task_template") or [])
	if not rows:
		for row in DEFAULT_SEA_IMPORT_TASK_TEMPLATE:
			settings.append("custom_sea_import_task_template", row)
		return True
	if _template_has_shipping_line_application(rows):
		return False

	subjects = [(row.task_subject or "").strip() for row in rows]
	if SHIPPING_LINE_FINANCE_SUBJECT not in subjects:
		return False

	new_rows: list[dict] = []
	for row in rows:
		subject = (row.task_subject or "").strip()
		new_rows.append(
			{
				"task_subject": row.task_subject,
				"department": row.department,
			}
		)
		if subject == "Finance Pays Entry Slip":
			new_rows.append(
				{
					"task_subject": SHIPPING_LINE_APPLICATION_SUBJECT,
					"department": "Documentation",
				}
			)

	settings.set("custom_sea_import_task_template", [])
	for row in new_rows:
		settings.append("custom_sea_import_task_template", row)
	return True


def _requirement_rows(settings) -> list:
	return list(settings.get("custom_sea_clearance_task_requirements") or [])


def _has_shipping_line_application(rows: list) -> bool:
	return any(r.requirement_type == "Shipping Line Application" for r in rows)


def _upgrade_requirements(settings) -> bool:
	rows = _requirement_rows(settings)
	if not rows:
		for row in build_requirement_seed_rows():
			settings.append("custom_sea_clearance_task_requirements", row)
		return True
	if _has_shipping_line_application(rows):
		return False

	old_finance_13 = any(
		int(r.sequence_no or 0) == 13
		and r.requirement_type == "Finance Payment"
		and (r.value or "").strip().upper() in ("STANDARD", "")
		for r in rows
	)
	if not old_finance_13:
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

	line_paid = next(
		(r for r in rows if (r.shipment_workflow_state or "").strip() == "Line Paid & DO Lodged"),
		None,
	)
	if line_paid and int(line_paid.min_completed_task_seq or 0) >= 15:
		return False

	settings.set("custom_sea_workflow_task_gates", [])
	for row in DEFAULT_SEA_WORKFLOW_TASK_GATES:
		settings.append("custom_sea_workflow_task_gates", row)
	return True


def _bump_container_seq_settings(settings) -> bool:
	meta = frappe.get_meta("CGM Shipping Settings")
	changed = False
	for fieldname, (_old, new) in CONTAINER_SEQ_FIELD_BUMPS.items():
		if not meta.has_field(fieldname):
			continue
		current = int(settings.get(fieldname) or 0)
		if current and current < new:
			settings.set(fieldname, new)
			changed = True
		elif not current:
			settings.set(fieldname, CONTAINER_TASK_SEQ_DEFAULTS.get(fieldname, new))
			changed = True
	return changed


def _shift_project_tasks(project: str) -> None:
	tasks = frappe.get_all(
		"Task",
		filters={"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY},
		fields=["name", "custom_sequence_no", "subject"],
		order_by="custom_sequence_no desc",
	)
	if not tasks:
		return

	has_application = any(
		(t.subject or "").strip() == SHIPPING_LINE_APPLICATION_SUBJECT for t in tasks
	)
	if has_application:
		return

	for task in tasks:
		seq = int(task.custom_sequence_no or 0)
		if seq >= 13:
			frappe.db.set_value(
				"Task",
				task.name,
				"custom_sequence_no",
				seq + 1,
				update_modified=False,
			)

	entry_finance = frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 12,
		},
		"name",
	)
	project_doc = frappe.get_doc("Project", project)
	new_task = frappe.new_doc("Task")
	new_task.subject = SHIPPING_LINE_APPLICATION_SUBJECT
	new_task.project = project
	new_task.custom_task_flow_key = SEA_TASK_FLOW_KEY
	new_task.custom_sequence_no = 13
	new_task.department = resolve_department_name("Documentation", company=project_doc.company)
	new_task.status = "Open"
	new_task.insert(ignore_permissions=True)

	if entry_finance:
		new_task.append("depends_on", {"task": entry_finance})
		new_task.save(ignore_permissions=True)

	finance_shipping = frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 14,
		},
		"name",
	)
	if finance_shipping:
		frappe.db.sql(
			"""
			DELETE FROM `tabTask Depends On`
			WHERE parent = %s AND task = %s
			""",
			(finance_shipping, entry_finance),
		)
		finance_doc = frappe.get_doc("Task", finance_shipping)
		finance_doc.append("depends_on", {"task": new_task.name})
		finance_doc.save(ignore_permissions=True)


def _upgrade_existing_project_tasks() -> None:
	if not frappe.db.has_column("Task", "custom_sequence_no"):
		return

	projects = frappe.get_all(
		"Task",
		filters={"custom_task_flow_key": SEA_TASK_FLOW_KEY},
		pluck="project",
		distinct=True,
	)
	for project in projects:
		if project:
			_shift_project_tasks(project)


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
	changed = _bump_container_seq_settings(settings) or changed

	if changed:
		settings.save(ignore_permissions=True)

	_upgrade_existing_project_tasks()
	frappe.db.commit()
