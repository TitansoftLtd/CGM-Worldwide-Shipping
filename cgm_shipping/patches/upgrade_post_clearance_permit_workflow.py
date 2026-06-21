"""Split post-clearance permits into application + finance tasks (existing sites)."""

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

OLD_POST_CLEARANCE_SUBJECT = "Prepare and pay Post-Clearance Permits"
POST_CLEARANCE_APPLICATION_SUBJECT = "Prepare Post-Clearance Permits"
POST_CLEARANCE_FINANCE_SUBJECT = "Finance pays for Post-Clearance Permits"

CONTAINER_SEQ_FIELD_BUMPS = {
	"custom_field_clearance_task_seq": (17, 18),
	"custom_kpa_paid_task_seq": (19, 20),
	"custom_book_trucks_task_seq": (20, 21),
	"custom_gate_out_task_seq": (21, 22),
	"custom_monitor_delivery_task_seq": (22, 23),
	"custom_offload_task_seq": (23, 24),
	"custom_empty_return_task_seq": (24, 25),
	"custom_interchange_task_seq": (25, 26),
}


def _template_has_post_clearance_finance(rows: list) -> bool:
	return any(
		(row.task_subject or "").strip() == POST_CLEARANCE_FINANCE_SUBJECT for row in rows
	)


def _upgrade_task_template(settings) -> bool:
	rows = list(settings.get("custom_sea_import_task_template") or [])
	if not rows:
		for row in DEFAULT_SEA_IMPORT_TASK_TEMPLATE:
			settings.append("custom_sea_import_task_template", row)
		return True
	if _template_has_post_clearance_finance(rows):
		return False

	subjects = [(row.task_subject or "").strip() for row in rows]
	if OLD_POST_CLEARANCE_SUBJECT not in subjects and POST_CLEARANCE_APPLICATION_SUBJECT not in subjects:
		return False

	new_rows: list[dict] = []
	for idx, row in enumerate(rows):
		subject = (row.task_subject or "").strip()
		if subject in (OLD_POST_CLEARANCE_SUBJECT, POST_CLEARANCE_APPLICATION_SUBJECT):
			new_rows.append(
				{
					"task_subject": POST_CLEARANCE_APPLICATION_SUBJECT,
					"department": row.department or "Declaration",
				}
			)
			next_subject = subjects[idx + 1] if idx + 1 < len(subjects) else ""
			if next_subject != POST_CLEARANCE_FINANCE_SUBJECT:
				new_rows.append(
					{
						"task_subject": POST_CLEARANCE_FINANCE_SUBJECT,
						"department": "Finance",
					}
				)
			continue
		new_rows.append(
			{
				"task_subject": row.task_subject,
				"department": row.department,
			}
		)

	settings.set("custom_sea_import_task_template", [])
	for row in new_rows:
		settings.append("custom_sea_import_task_template", row)
	return True


def _requirement_rows(settings) -> list:
	return list(settings.get("custom_sea_clearance_task_requirements") or [])


def _has_post_clearance_finance_requirement(rows: list) -> bool:
	return any(
		int(r.sequence_no or 0) == 17
		and r.requirement_type == "Finance Payment"
		and (r.value or "").strip() == "Permit"
		for r in rows
	)


def _upgrade_requirements(settings) -> bool:
	rows = _requirement_rows(settings)
	if not rows:
		for row in build_requirement_seed_rows():
			settings.append("custom_sea_clearance_task_requirements", row)
		return True
	if _has_post_clearance_finance_requirement(rows):
		return False

	old_field_gate_seq = any(
		int(r.sequence_no or 0) == 17
		and r.requirement_type == "Document"
		and (r.value or "").strip() == "FIELD"
		for r in rows
	)
	if not old_field_gate_seq and not any(
		int(r.sequence_no or 0) == 16 and r.requirement_type == "Permit Application" for r in rows
	):
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

	field_gate = next(
		(r for r in rows if (r.shipment_workflow_state or "").strip() == "Field Clearance"),
		None,
	)
	if field_gate and int(field_gate.min_completed_task_seq or 0) >= 18:
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

	if any(
		(t.subject or "").strip() == POST_CLEARANCE_FINANCE_SUBJECT
		and int(t.custom_sequence_no or 0) == 17
		for t in tasks
	):
		return

	application = next((t for t in tasks if int(t.custom_sequence_no or 0) == 16), None)
	if not application:
		return

	subject = (application.subject or "").strip()
	if subject == OLD_POST_CLEARANCE_SUBJECT:
		frappe.db.set_value(
			"Task",
			application.name,
			"subject",
			POST_CLEARANCE_APPLICATION_SUBJECT,
			update_modified=False,
		)
	elif subject != POST_CLEARANCE_APPLICATION_SUBJECT:
		return

	for task in tasks:
		seq = int(task.custom_sequence_no or 0)
		if seq >= 17:
			frappe.db.set_value(
				"Task",
				task.name,
				"custom_sequence_no",
				seq + 1,
				update_modified=False,
			)

	app_name = application.name
	project_doc = frappe.get_doc("Project", project)
	new_task = frappe.new_doc("Task")
	new_task.subject = POST_CLEARANCE_FINANCE_SUBJECT
	new_task.project = project
	new_task.custom_task_flow_key = SEA_TASK_FLOW_KEY
	new_task.custom_sequence_no = 17
	new_task.department = resolve_department_name("Finance", company=project_doc.company)
	new_task.status = "Open"
	new_task.insert(ignore_permissions=True)
	new_task.append("depends_on", {"task": app_name})
	new_task.save(ignore_permissions=True)

	field_clearance = frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 18,
		},
		"name",
	)
	if field_clearance:
		frappe.db.sql(
			"""
			DELETE FROM `tabTask Depends On`
			WHERE parent = %s AND task = %s
			""",
			(field_clearance, app_name),
		)
		existing = frappe.db.exists(
			"Task Depends On",
			{"parent": field_clearance, "task": new_task.name},
		)
		if not existing:
			frappe.get_doc(
				{
					"doctype": "Task Depends On",
					"parent": field_clearance,
					"parenttype": "Task",
					"parentfield": "depends_on",
					"task": new_task.name,
				}
			).insert(ignore_permissions=True)


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
