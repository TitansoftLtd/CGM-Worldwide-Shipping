from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	SEA_IMPORT_TEMPLATE,
	normalize_template_name,
)


def create_project_tasks(project_name: str) -> list[str]:
	"""
	Create tasks for a project based on its shipment type's linked CGM Task Template.
	Returns list of created task names. Called once when a Project is created.
	"""
	project = frappe.get_doc("Project", project_name)
	shipment_type_name = project.get("custom_shipment_type")

	if not shipment_type_name:
		frappe.logger("task_engine").info(
			f"Project {project_name} has no shipment type. No tasks created."
		)
		return []

	template_name = _resolve_template(shipment_type_name)

	if not template_name:
		frappe.logger("task_engine").info(
			f"No task template for shipment type {shipment_type_name}. No tasks created."
		)
		return []

	if frappe.db.exists(
		"Task",
		{"project": project_name, "custom_task_flow_key": ["!=", ""]},
	):
		frappe.logger("task_engine").info(
			f"Project {project_name} already has workflow tasks. Skipping creation."
		)
		return []

	created = _create_from_template(template_name, project, shipment_type_name)
	_run_post_create_automation(project_name, template_name)
	return created


def _resolve_template(shipment_type_name: str) -> str | None:
	"""
	Find the CGM Task Template for a shipment type.
	Priority:
	1. task_template Link field on Shipment Type (preferred)
	2. Legacy task_flow_key mapping
	3. None — no tasks created, no error
	"""
	fields = ["task_template"]
	if frappe.get_meta("Shipment Type").has_field("task_flow_key"):
		fields.append("task_flow_key")

	st = frappe.db.get_value("Shipment Type", shipment_type_name, fields, as_dict=True)

	if not st:
		return None

	if st.get("task_template"):
		return st.task_template

	# Legacy task_flow_key → template name
	if st.get("task_flow_key"):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
			LEGACY_FLOW_KEY_TO_TEMPLATE,
		)

		mapped = LEGACY_FLOW_KEY_TO_TEMPLATE.get(str(st.task_flow_key).strip())
		if mapped and frappe.db.exists("CGM Task Template", mapped):
			return mapped

	return None


def _create_from_template(
	template_name: str,
	project,
	shipment_type_name: str,
) -> list[str]:
	"""Load CGM Task Template (including extended parent if set), create Task records."""
	if not frappe.db.exists("CGM Task Template", template_name):
		frappe.logger("task_engine").warning(
			f"Task template {template_name} not found. No tasks created for {project.name}."
		)
		return []

	template = frappe.get_doc("CGM Task Template", template_name)

	if not template.is_active:
		frappe.logger("task_engine").warning(
			f"Task template {template_name} is inactive. No tasks created for {project.name}."
		)
		return []

	all_items = _collect_items(template)

	if not all_items:
		return []

	company_abbr = _get_company_abbr(project.company)
	created: dict[int, str] = {}

	frappe.flags.cgm_skip_task_project_sync = True
	try:
		for item in sorted(all_items, key=lambda x: x["sequence_no"]):
			task_name = _create_single_task(
				item=item,
				project=project,
				template_name=template_name,
				company_abbr=company_abbr,
				created_map=created,
			)
			created[item["sequence_no"]] = task_name
	finally:
		frappe.flags.cgm_skip_task_project_sync = False

	return list(created.values())


def _collect_items(template, _visited: set | None = None) -> list[dict]:
	"""Recursively collect task items following extends_template."""
	if _visited is None:
		_visited = set()

	if template.name in _visited:
		frappe.logger("task_engine").warning(
			f"Circular extends_template detected at {template.name}. Breaking cycle."
		)
		return []

	_visited.add(template.name)
	items: list[dict] = []

	if template.extends_template:
		parent = frappe.get_doc("CGM Task Template", template.extends_template)
		items.extend(_collect_items(parent, _visited))

	max_parent_seq = max((i["sequence_no"] for i in items), default=0)

	for row in template.tasks:
		items.append(
			{
				"sequence_no": int(row.sequence_no or 0) + max_parent_seq,
				"subject": row.subject,
				"department_role": row.department_role,
				"description": row.description or "",
				"depends_on_sequences": row.depends_on_sequences or "",
				"requires_finance_action": bool(row.requires_finance_action),
				"requires_document_upload": bool(row.requires_document_upload),
				"requires_container_update": bool(row.requires_container_update),
				"requires_permit_action": bool(row.requires_permit_action),
				"is_auto_completable": bool(row.is_auto_completable),
				"completion_condition": row.completion_condition or "",
				"is_optional": bool(row.is_optional),
			}
		)

	return items


def _create_single_task(
	item: dict,
	project,
	template_name: str,
	company_abbr: str,
	created_map: dict,
) -> str:
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		resolve_department_name,
	)

	dept_stem = (item.get("department_role") or "").strip()
	department = f"{dept_stem} - {company_abbr}" if company_abbr else dept_stem

	task = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": item["subject"],
			"project": project.name,
			"description": item.get("description") or "",
			"department": department,
			"company": project.company,
			"status": "Open",
			"priority": "Low",
			"custom_task_flow_key": template_name,
			"custom_sequence_no": item["sequence_no"],
		}
	)

	if item.get("depends_on_sequences"):
		seq_nums = [
			int(s.strip())
			for s in str(item["depends_on_sequences"]).split(",")
			if s.strip().isdigit()
		]
		for seq in seq_nums:
			parent_task = created_map.get(seq)
			if parent_task:
				task.append("depends_on", {"task": parent_task})

	task.insert(ignore_permissions=True)
	# Workflow tasks belong to the process, not the user who clicked Start Shipment —
	# otherwise Declarants who create the plan become owner of every step and see all tasks.
	if task.owner != "Administrator" and frappe.db.exists("User", "Administrator"):
		frappe.db.set_value("Task", task.name, "owner", "Administrator", update_modified=False)
		task.owner = "Administrator"
	return task.name


def _get_company_abbr(company: str) -> str:
	if not company:
		default_company = frappe.db.get_single_value(
			"CGM Shipping Settings", "default_company"
		)
		company = default_company or ""

	if not company:
		return ""

	return frappe.db.get_value("Company", company, "abbr") or ""


def _run_post_create_automation(project_name: str, template_name: str) -> None:
	"""Intake auto-complete and document carry when CRM documents are ready."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		carry_project_documents_to_sea_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
		project_ready_for_documents_received,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_TRANSIT_IMPORT_TEMPLATE,
	)

	normalized = normalize_template_name(template_name)
	if normalized not in (SEA_IMPORT_TEMPLATE, SEA_TRANSIT_IMPORT_TEMPLATE):
		return

	project_doc = frappe.get_doc("Project", project_name)
	if not project_ready_for_documents_received(project_doc):
		return

	carry_project_documents_to_sea_tasks(project_name)
	_auto_complete_intake_tasks(project_name, template_name)


def _auto_complete_intake_tasks(project_name: str, template_name: str) -> None:
	"""Mark template intake tasks complete (sequences from Settings auto-complete list)."""
	from frappe.utils import now_datetime

	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		AUTO_COMPLETE_INTAKE_REMARK,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		auto_complete_sequences,
	)

	for seq in sorted(auto_complete_sequences()):
		task_name = frappe.db.get_value(
			"Task",
			{
				"project": project_name,
				"custom_task_flow_key": template_name,
				"custom_sequence_no": seq,
			},
			"name",
		)
		if not task_name:
			continue
		if frappe.db.get_value("Task", task_name, "status") == "Completed":
			continue
		task = frappe.get_doc("Task", task_name)
		task.status = "Completed"
		task.completed_by = frappe.session.user
		task.completed_on = now_datetime()
		task.description = AUTO_COMPLETE_INTAKE_REMARK
		frappe.flags.cgm_auto_completing_sea_task = True
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_auto_completing_sea_task = False


def check_auto_completable_tasks(project_name: str) -> None:
	"""Called on Project save. Marks open auto-completable tasks complete when condition met."""
	project = frappe.get_doc("Project", project_name)

	open_tasks = frappe.get_all(
		"Task",
		filters={
			"project": project_name,
			"status": "Open",
			"custom_task_flow_key": ["!=", ""],
		},
		fields=["name", "custom_sequence_no", "custom_task_flow_key"],
	)

	if not open_tasks:
		return

	templates_seen: dict[str, dict] = {}

	for task_rec in open_tasks:
		tpl_name = normalize_template_name(task_rec.custom_task_flow_key)
		if not tpl_name or not frappe.db.exists("CGM Task Template", tpl_name):
			continue

		if tpl_name not in templates_seen:
			templates_seen[tpl_name] = {
				item["sequence_no"]: item
				for item in _collect_items(frappe.get_doc("CGM Task Template", tpl_name))
				if item.get("is_auto_completable")
			}

		auto_items = templates_seen[tpl_name]
		seq = task_rec.custom_sequence_no
		item = auto_items.get(seq)

		if not item:
			continue

		condition = item.get("completion_condition", "")
		if not condition:
			continue

		if _condition_met(condition, project):
			frappe.db.set_value("Task", task_rec.name, "status", "Completed")


def _condition_met(condition: str, project) -> bool:
	"""Evaluate a dot-path condition against the project doc."""
	if not condition:
		return False

	parts = condition.strip().split(".", 1)
	if len(parts) != 2 or parts[0] != "project":
		return False

	field = parts[1]
	return bool(project.get(field))


def on_project_after_insert(doc, method=None) -> None:
	create_project_tasks(doc.name)


def on_project_update(doc, method=None) -> None:
	check_auto_completable_tasks(doc.name)
