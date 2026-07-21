"""Sea transit clearance task plans — composed from CGM Shipping Settings templates."""

from __future__ import annotations

import frappe
from frappe.utils import cint

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SEA_TRANSIT_EXPORT_TASK_FLOW_KEY,
	SEA_TRANSIT_IMPORT_TASK_FLOW_KEY,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
	AUTO_COMPLETE_INTAKE_REMARK,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	get_task_flow_key_for_shipment_type,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	SEA_TRANSIT_EXPORT_TEMPLATE,
	SEA_TRANSIT_IMPORT_TEMPLATE,
	normalize_template_name,
	stored_task_flow_key,
	task_flow_key_in_filter,
	workflow_flow_keys_for_template,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	load_sea_transit_export_task_template,
	load_sea_transit_import_task_template,
)


def auto_complete_initial_transit_import_tasks(project: str) -> list[str]:
	"""Attach Project docs to auto-complete steps 1–2 on sea transit import tasks."""
	from frappe.utils import now_datetime

	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		carry_project_documents_to_sea_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		auto_complete_sequences,
	)

	carry_project_documents_to_sea_tasks(project)

	completed = []
	for seq in sorted(auto_complete_sequences()):
		task_name = None
		for flow_key in workflow_flow_keys_for_template(SEA_TRANSIT_IMPORT_TEMPLATE):
			task_name = frappe.db.get_value(
				"Task",
				{
					"project": project,
					"custom_task_flow_key": flow_key,
					"custom_sequence_no": seq,
				},
				"name",
			)
			if task_name:
				break
		if not task_name:
			continue
		if frappe.db.get_value("Task", task_name, "status") == "Completed":
			completed.append(task_name)
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
		completed.append(task_name)
	return completed


def bootstrap_transit_task_plan_for_project(project_name: str) -> dict | None:
	"""Create sea transit import/export task plans when Shipment Type task_flow_key matches."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
		project_ready_for_documents_received,
	)

	project_doc = frappe.get_doc("Project", project_name)
	flow_key = get_task_flow_key_for_shipment_type(project_doc.get("custom_shipment_type"))
	if not flow_key:
		return None

	normalized = normalize_template_name(flow_key) or flow_key

	if normalized == SEA_TRANSIT_IMPORT_TEMPLATE or flow_key == SEA_TRANSIT_IMPORT_TASK_FLOW_KEY:
		if not project_ready_for_documents_received(project_doc):
			return None
		if frappe.db.exists(
			"Task",
			{
				"project": project_name,
				"custom_task_flow_key": task_flow_key_in_filter(SEA_TRANSIT_IMPORT_TEMPLATE),
			},
		):
			done = auto_complete_initial_transit_import_tasks(project_name)
			return {"auto_completed": done, "created": 0}
		result = create_sea_transit_import_task_plan_internal(project_name)
		result["auto_completed"] = auto_complete_initial_transit_import_tasks(project_name)
		return result

	if normalized == SEA_TRANSIT_EXPORT_TEMPLATE or flow_key == SEA_TRANSIT_EXPORT_TASK_FLOW_KEY:
		if frappe.db.exists(
			"Task",
			{
				"project": project_name,
				"custom_task_flow_key": task_flow_key_in_filter(SEA_TRANSIT_EXPORT_TEMPLATE),
			},
		):
			return {"created": 0}
		return create_sea_transit_export_task_plan_internal(project_name)

	return None


def create_sea_transit_import_task_plan_internal(project: str, reset: bool = False) -> dict:
	"""Compose sea import shared steps + transit extension from Settings."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		resolve_department_name,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		ensure_sea_task_requirements_configured,
	)

	ensure_sea_task_requirements_configured()
	project_doc = frappe.get_doc("Project", project)
	flow_filter = task_flow_key_in_filter(SEA_TRANSIT_IMPORT_TEMPLATE)
	canonical_flow_key = stored_task_flow_key(SEA_TRANSIT_IMPORT_TEMPLATE)

	existing = frappe.get_all(
		"Task",
		filters={"project": project, "custom_task_flow_key": flow_filter},
		pluck="name",
		limit=1,
	)
	if existing and not cint(reset):
		frappe.throw("Sea transit import task plan already exists. Use reset=1 to regenerate.")
	if existing and cint(reset):
		for name in frappe.get_all(
			"Task",
			filters={"project": project, "custom_task_flow_key": flow_filter},
			pluck="name",
		):
			frappe.delete_doc("Task", name, ignore_permissions=True, force=True)

	task_template = load_sea_transit_import_task_template()
	created: list[str] = []
	prev_task = None

	frappe.flags.cgm_skip_task_project_sync = True
	try:
		for idx, item in enumerate(task_template, start=1):
			subject = item.get("subject")
			if not subject:
				frappe.throw(f"Transit import task template item at position {idx} has no subject.")

			task = frappe.new_doc("Task")
			task.subject = subject
			task.project = project
			task.custom_task_flow_key = canonical_flow_key
			task.custom_sequence_no = int(item.get("sequence_no") or idx)
			task.department = resolve_department_name(
				item.get("department"), company=project_doc.company
			)
			task.status = "Open"
			if prev_task:
				task.append("depends_on", {"task": prev_task.name})
			task.insert(ignore_permissions=True)
			prev_task = task
			created.append(task.name)
	finally:
		frappe.flags.cgm_skip_task_project_sync = False

	return {"created": created, "count": len(created)}


def create_sea_transit_export_task_plan_internal(project: str, reset: bool = False) -> dict:
	"""Create the sea transit export task plan from Settings."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		resolve_department_name,
	)

	project_doc = frappe.get_doc("Project", project)
	flow_filter = task_flow_key_in_filter(SEA_TRANSIT_EXPORT_TEMPLATE)
	canonical_flow_key = stored_task_flow_key(SEA_TRANSIT_EXPORT_TEMPLATE)

	existing = frappe.get_all(
		"Task",
		filters={"project": project, "custom_task_flow_key": flow_filter},
		pluck="name",
		limit=1,
	)
	if existing and not cint(reset):
		frappe.throw("Sea transit export task plan already exists. Use reset=1 to regenerate.")
	if existing and cint(reset):
		for name in frappe.get_all(
			"Task",
			filters={"project": project, "custom_task_flow_key": flow_filter},
			pluck="name",
		):
			frappe.delete_doc("Task", name, ignore_permissions=True, force=True)

	task_template = load_sea_transit_export_task_template()
	created: list[str] = []
	prev_task = None

	frappe.flags.cgm_skip_task_project_sync = True
	try:
		for idx, item in enumerate(task_template, start=1):
			subject = item.get("subject")
			if not subject:
				frappe.throw(f"Transit export task template item at position {idx} has no subject.")

			task = frappe.new_doc("Task")
			task.subject = subject
			task.project = project
			task.custom_task_flow_key = canonical_flow_key
			task.custom_sequence_no = idx
			task.department = resolve_department_name(
				item.get("department"), company=project_doc.company
			)
			task.status = "Open"
			if prev_task:
				task.append("depends_on", {"task": prev_task.name})
			task.insert(ignore_permissions=True)
			prev_task = task
			created.append(task.name)
	finally:
		frappe.flags.cgm_skip_task_project_sync = False

	return {"created": created, "count": len(created)}
