"""Load workflow tasks on a Project for any CGM Task Template."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	get_task_flow_key_for_shipment_type,
	get_task_template_for_shipment_type,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	ALL_TEMPLATE_NAMES,
	ROAD_TRANSIT_INBOUND_TEMPLATE,
	SEA_IMPORT_TEMPLATE,
	SEA_TRANSIT_IMPORT_TEMPLATE,
	normalize_template_name,
	workflow_flow_keys_for_template,
)


GENERIC_WORKFLOW_STATES = ("Draft", "In Progress", "Completed")


def get_project_workflow_flow_keys(project) -> tuple[str, ...]:
	"""All custom_task_flow_key values that belong to this project's workflow."""
	project_name = project if isinstance(project, str) else project.name
	shipment_type = None if isinstance(project, str) else project.get("custom_shipment_type")
	return _workflow_flow_keys(project_name, shipment_type)


@frappe.request_cache
def _workflow_flow_keys(project_name: str, shipment_type: str | None) -> tuple[str, ...]:
	"""Cached per request — a single dashboard load asks for these half a dozen times."""
	keys: list[str] = []

	if shipment_type:
		template = get_task_template_for_shipment_type(shipment_type)
		keys.extend(workflow_flow_keys_for_template(template))
		flow = get_task_flow_key_for_shipment_type(shipment_type)
		if flow:
			keys.extend(workflow_flow_keys_for_template(normalize_template_name(flow) or flow))

	for flow_key in frappe.get_all(
		"Task",
		filters={"project": project_name, "custom_task_flow_key": ["!=", ""]},
		pluck="custom_task_flow_key",
		distinct=True,
	):
		value = (flow_key or "").strip()
		if not value:
			continue
		keys.append(value)
		normalized = normalize_template_name(value)
		if normalized:
			keys.extend(workflow_flow_keys_for_template(normalized))

	seen: set[str] = set()
	ordered: list[str] = []
	for key in keys:
		if key and key not in seen:
			seen.add(key)
			ordered.append(key)
	return tuple(ordered)


def project_has_workflow_tasks(project) -> bool:
	project_name = project if isinstance(project, str) else project.name
	flow_keys = get_project_workflow_flow_keys(project)
	if flow_keys:
		return bool(
			frappe.db.exists(
				"Task",
				{"project": project_name, "custom_task_flow_key": ["in", list(flow_keys)]},
			)
		)
	return bool(
		frappe.db.exists(
			"Task",
			{"project": project_name, "custom_task_flow_key": ["!=", ""]},
		)
	)


@frappe.whitelist()
def get_project_workflow_flow_keys_api(project: str) -> list[str]:
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	return list(get_project_workflow_flow_keys(project))


def project_uses_clearance_workflow_states(project) -> bool:
	"""Sea import / transit import / road transit inbound use clearance status pills."""
	for key in get_project_workflow_flow_keys(project):
		normalized = normalize_template_name(key)
		if normalized in (
			SEA_IMPORT_TEMPLATE,
			SEA_TRANSIT_IMPORT_TEMPLATE,
			ROAD_TRANSIT_INBOUND_TEMPLATE,
		):
			return True
	# Shipment type alone (tasks not yet created / flow key missing).
	shipment_type = None if isinstance(project, str) else project.get("custom_shipment_type")
	if shipment_type:
		template = get_task_template_for_shipment_type(shipment_type)
		if template == ROAD_TRANSIT_INBOUND_TEMPLATE:
			return True
	return False


def project_is_road_transit_inbound(project) -> bool:
	for key in get_project_workflow_flow_keys(project):
		if normalize_template_name(key) == ROAD_TRANSIT_INBOUND_TEMPLATE:
			return True
	shipment_type = None if isinstance(project, str) else project.get("custom_shipment_type")
	if shipment_type and get_task_template_for_shipment_type(shipment_type) == ROAD_TRANSIT_INBOUND_TEMPLATE:
		return True
	return False


def get_clearance_workflow_states_for_project(project) -> list[str]:
	"""Ordered status pills for the Project clearance chart."""
	if project_is_road_transit_inbound(project):
		from cgm_shipping.cgm_worldwide_shipping.customizations.road_transit_inbound_workflow import (
			get_road_transit_inbound_workflow_states,
		)

		return get_road_transit_inbound_workflow_states()
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		get_tracking_workflow_states,
	)

	return get_tracking_workflow_states()


def get_clearance_workflow_gates_for_project(project) -> dict[str, dict]:
	"""State → gate metadata used to derive progress from completed task sequences."""
	if project_is_road_transit_inbound(project):
		from cgm_shipping.cgm_worldwide_shipping.customizations.road_transit_inbound_workflow import (
			get_road_transit_inbound_workflow_gates,
		)

		return get_road_transit_inbound_workflow_gates()
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_workflow_task_gates,
	)

	return get_workflow_task_gates()


def get_workflow_template_name(project) -> str | None:
	flow_keys = get_project_workflow_flow_keys(project)
	for key in flow_keys:
		normalized = normalize_template_name(key)
		if normalized in ALL_TEMPLATE_NAMES:
			return normalized
	return normalize_template_name(flow_keys[0]) if flow_keys else None


def get_workflow_tasks_for_project(
	project,
	fields: list[str] | None = None,
	*,
	open_only: bool = False,
	limit: int = 50,
) -> list[dict]:
	project_name = project if isinstance(project, str) else project.name
	flow_keys = get_project_workflow_flow_keys(project)
	if not flow_keys:
		return []

	default_fields = [
		"name",
		"subject",
		"custom_sequence_no",
		"status",
		"department",
		"owner",
		"_assign",
		"custom_permit_invoices_submitted",
	]
	query_fields = fields or default_fields
	filters: dict = {
		"project": project_name,
		"custom_task_flow_key": ["in", list(flow_keys)],
	}
	if open_only:
		filters["status"] = ["not in", ["Completed", "Cancelled"]]

	rows = frappe.get_all(
		"Task",
		filters=filters,
		fields=query_fields,
		order_by="custom_sequence_no asc",
		limit=limit,
	)
	for row in rows:
		if "custom_sequence_no" in row and "seq" not in row:
			row["seq"] = row.get("custom_sequence_no")
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		filter_sea_tasks_for_user,
	)

	return filter_sea_tasks_for_user(rows)


def get_all_workflow_tasks_for_project(project: str, user: str | None = None) -> list[dict]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		filter_sea_tasks_for_user,
	)

	rows = get_workflow_tasks_for_project(project, limit=100)
	return filter_sea_tasks_for_user(rows, user=user)


def get_open_workflow_tasks_for_project(project: str, user: str | None = None) -> list[dict]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		filter_sea_tasks_for_user,
	)

	rows = get_workflow_tasks_for_project(project, open_only=True, limit=100)
	return filter_sea_tasks_for_user(rows, user=user)


def derive_generic_workflow_progress(tasks: list) -> tuple[str, int]:
	states = list(GENERIC_WORKFLOW_STATES)
	if not tasks:
		return states[0], 0
	completed = sum(1 for row in tasks if row.get("status") == "Completed")
	if completed <= 0:
		return states[0], 0
	if completed >= len(tasks):
		return states[2], 2
	return states[1], 1


def workflow_task_count_for_project(project) -> int:
	template = get_workflow_template_name(project)
	if template and frappe.db.exists("CGM Task Template", template):
		from cgm_shipping.cgm_worldwide_shipping.task_engine import _collect_items

		template_doc = frappe.get_doc("CGM Task Template", template)
		return len(_collect_items(template_doc))
	return len(get_workflow_tasks_for_project(project, fields=["name"], limit=100))
