# Copyright (c) 2026, Titansoft Limited and contributors
"""Container Allocation business logic and desk helpers."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate, today

ALLOCATION_STATUS_DRAFT = "Draft"
ALLOCATION_STATUS_ALLOCATED = "Allocated"
ALLOCATION_STATUS_ACKNOWLEDGED = "Acknowledged"
ALLOCATION_STATUS_COMPLETED = "Completed"

ASSIGNMENT_PENDING = "Pending"
ASSIGNMENT_TRUCK = "Truck Assigned"
ASSIGNMENT_INTERCHANGE = "Interchange Uploaded"

PENDING_TRUCK_THRESHOLD_DAYS = 2


def validate_transporter_supplier(transporter: str | None) -> None:
	if not transporter:
		return
	if not frappe.db.get_value("Supplier", transporter, "is_transporter"):
		frappe.throw(
			_("Supplier {0} is not marked as a transporter.").format(
				frappe.bold(transporter)
			)
		)


def get_active_allocation_for_tracker(
	container_tracker: str, exclude_allocation: str | None = None
) -> str | None:
	"""Return name of a submitted, non-completed allocation holding this tracker."""
	filters: dict[str, Any] = {
		"docstatus": 1,
		"status": ("in", (ALLOCATION_STATUS_ALLOCATED, ALLOCATION_STATUS_ACKNOWLEDGED)),
	}
	if exclude_allocation:
		filters["name"] = ("!=", exclude_allocation)

	rows = frappe.get_all(
		"Container Allocation",
		filters=filters,
		pluck="name",
	)
	if not rows:
		return None

	for allocation_name in rows:
		if frappe.db.exists(
			"Container Allocation Item",
			{"parent": allocation_name, "container_tracker": container_tracker},
		):
			return allocation_name
	return None


def validate_active_allocation_uniqueness(doc) -> None:
	if doc.docstatus == 2:
		return
	for row in doc.containers or []:
		if not row.container_tracker:
			continue
		existing = get_active_allocation_for_tracker(row.container_tracker, doc.name)
		if existing:
			frappe.throw(
				_(
					"Container Tracker {0} is already allocated on {1}. "
					"Cancel or complete that allocation before re-allocating."
				).format(
					frappe.bold(row.container_tracker),
					frappe.bold(existing),
				)
			)


def assign_trackers_on_submit(doc) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
		_derive_container_mode,
	)

	project = frappe.get_cached_doc("Project", doc.project)
	default_mode = _derive_container_mode(project)

	for row in doc.containers or []:
		if not row.container_tracker:
			continue
		updates: dict[str, Any] = {"transporter": doc.transporter}
		current_mode = frappe.db.get_value(
			"Container Tracker", row.container_tracker, "container_mode"
		)
		if not current_mode:
			updates["container_mode"] = default_mode
		frappe.db.set_value(
			"Container Tracker", row.container_tracker, updates, update_modified=True
		)
		frappe.clear_document_cache("Container Tracker", row.container_tracker)


def get_allocated_tracker_names(project: str | None = None) -> set[str]:
	"""Trackers on submitted, non-completed allocations (optionally scoped to project)."""
	filters: dict[str, Any] = {
		"docstatus": 1,
		"status": ("in", (ALLOCATION_STATUS_ALLOCATED, ALLOCATION_STATUS_ACKNOWLEDGED)),
	}
	if project:
		filters["project"] = project

	allocation_names = frappe.get_all("Container Allocation", filters=filters, pluck="name")
	if not allocation_names:
		return set()

	return set(
		frappe.get_all(
			"Container Allocation Item",
			filters={"parent": ("in", allocation_names)},
			pluck="container_tracker",
		)
	)


def build_unallocated_container_rows(project: str) -> list[dict]:
	"""Unallocated Container Tracker rows for a project, de-duplicated by tracker."""
	project_doc = frappe.get_cached_doc("Project", project)
	allocated = get_allocated_tracker_names(project)
	containers: list[dict] = []
	seen: set[str] = set()

	def _append_tracker(tracker: str, container_number: str = "", cargo_type: str = "") -> None:
		if not tracker or tracker in allocated or tracker in seen:
			return
		if not frappe.db.exists("Container Tracker", tracker):
			return
		tracker_values = frappe.db.get_value(
			"Container Tracker",
			tracker,
			["container_number", "cargo_type"],
			as_dict=True,
		) or {}
		containers.append(
			{
				"container_tracker": tracker,
				"container_number": container_number or tracker_values.get("container_number") or "",
				"cargo_type": cargo_type or tracker_values.get("cargo_type") or "",
				"assignment_status": ASSIGNMENT_PENDING,
			}
		)
		seen.add(tracker)

	for row in project_doc.get("custom_container_information") or []:
		tracker = row.container_tracker
		if not tracker and row.container_number:
			tracker = frappe.db.get_value(
				"Container Tracker",
				{"project": project, "container_number": row.container_number},
				"name",
			)
		_append_tracker(
			tracker,
			row.container_number or "",
			row.cargo_type or "",
		)

	for tracker_row in frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=["name", "container_number", "cargo_type"],
		order_by="container_number asc",
	):
		_append_tracker(
			tracker_row.name,
			tracker_row.container_number or "",
			tracker_row.cargo_type or "",
		)

	return containers


@frappe.whitelist()
def get_container_allocation_defaults(project: str) -> dict:
	"""Pre-fill a new Container Allocation from a Project's unallocated containers."""
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	frappe.has_permission("Container Allocation", ptype="create", throw=True)

	project_doc = frappe.get_doc("Project", project)
	return {
		"project": project,
		"bill_of_lading": project_doc.get("custom_bill_of_lading") or "",
		"allocation_date": today(),
		"allocated_by": frappe.session.user,
		"status": ALLOCATION_STATUS_DRAFT,
		"containers": build_unallocated_container_rows(project),
	}


def get_allocation_map_for_trackers(tracker_names: list[str]) -> dict[str, dict]:
	"""Batch lookup of active allocation info keyed by container_tracker."""
	if not tracker_names or not frappe.db.exists("DocType", "Container Allocation"):
		return {}

	placeholders = ", ".join(["%s"] * len(tracker_names))
	rows = frappe.db.sql(
		f"""
		SELECT
			item.container_tracker,
			ca.name AS allocation,
			ca.transporter,
			ca.allocation_date,
			ca.status AS allocation_status,
			item.assignment_status,
			item.name AS allocation_item
		FROM `tabContainer Allocation Item` item
		INNER JOIN `tabContainer Allocation` ca ON ca.name = item.parent
		WHERE item.container_tracker IN ({placeholders})
			AND ca.docstatus = 1
			AND ca.status IN (%s, %s)
		""",
		(*tracker_names, ALLOCATION_STATUS_ALLOCATED, ALLOCATION_STATUS_ACKNOWLEDGED),
		as_dict=True,
	)

	out: dict[str, dict] = {}
	for row in rows:
		out[row.container_tracker] = row
	return out


def enrich_containers_with_allocation(containers: list[dict]) -> list[dict]:
	tracker_names = [c.get("name") for c in containers if c.get("name")]
	allocation_map = get_allocation_map_for_trackers(tracker_names)
	ref_date = getdate(today())

	for container in containers:
		info = allocation_map.get(container.get("name"))
		if not info:
			container["allocation"] = None
			continue

		container["allocation"] = info.allocation
		container["allocation_transporter"] = info.transporter
		container["allocation_date"] = info.allocation_date
		container["allocation_status"] = info.allocation_status
		container["assignment_status"] = info.assignment_status

		if (
			info.assignment_status == ASSIGNMENT_PENDING
			and info.allocation_date
			and (ref_date - getdate(info.allocation_date)).days >= PENDING_TRUCK_THRESHOLD_DAYS
		):
			container["allocation_pending_alert"] = True
		else:
			container["allocation_pending_alert"] = False

	return containers


def _update_allocation_item_row(item_name: str, values: dict) -> None:
	"""Update a child row on a submitted allocation without tripping submit guards."""
	frappe.db.set_value("Container Allocation Item", item_name, values, update_modified=False)


def save_assignment_draft(
	allocation_name: str,
	item_name: str,
	truck_number: str,
	driver_name: str,
	driver_contact: str = "",
) -> dict:
	"""Save truck/driver on the allocation row only — status stays Pending."""
	_get_allocation_item_row(allocation_name, item_name)
	_update_allocation_item_row(
		item_name,
		{
			"truck_number": (truck_number or "").strip(),
			"driver_name": (driver_name or "").strip(),
			"driver_contact": (driver_contact or "").strip(),
		},
	)
	return {
		"ok": True,
		"assignment_status": ASSIGNMENT_PENDING,
		"message": _("Draft saved. Submit assignment when ready — CGM is notified only after submit."),
	}


def submit_truck_assignment(
	allocation_name: str,
	item_name: str,
	truck_number: str,
	driver_name: str,
	driver_contact: str = "",
) -> dict:
	"""Confirm assignment: update allocation row and sync Container Tracker."""
	item = _get_allocation_item_row(allocation_name, item_name)

	if not (truck_number or "").strip():
		frappe.throw(_("Enter the truck number before submitting the assignment."))
	if not (driver_name or "").strip():
		frappe.throw(_("Enter the driver name before submitting the assignment."))

	truck_number = truck_number.strip()
	driver_name = driver_name.strip()
	driver_contact = (driver_contact or "").strip()

	_update_allocation_item_row(
		item_name,
		{
			"truck_number": truck_number,
			"driver_name": driver_name,
			"driver_contact": driver_contact,
			"assignment_status": ASSIGNMENT_TRUCK,
		},
	)

	tracker = frappe.get_doc("Container Tracker", item.container_tracker, ignore_permissions=True)
	tracker.truck_number = truck_number
	tracker.driver_name = driver_name
	tracker.driver_contact = driver_contact
	tracker.save(ignore_permissions=True)

	return {"ok": True, "assignment_status": ASSIGNMENT_TRUCK}


def sync_truck_assignment_from_item(
	allocation_name: str,
	item_name: str,
	truck_number: str,
	driver_name: str,
	driver_contact: str,
) -> dict:
	"""Backward-compatible alias for submit."""
	return submit_truck_assignment(
		allocation_name,
		item_name,
		truck_number,
		driver_name,
		driver_contact,
	)


def sync_interchange_from_item(
	allocation_name: str,
	item_name: str,
	interchange_document: str,
	interchange_date: str | None = None,
) -> dict:
	"""Confirm interchange: sync to Container Tracker and mark row complete."""
	allocation = frappe.get_doc("Container Allocation", allocation_name, ignore_permissions=True)
	item = _get_allocation_item(allocation, item_name)

	if item.assignment_status not in (ASSIGNMENT_TRUCK, ASSIGNMENT_INTERCHANGE):
		frappe.throw(_("Interchange can only be submitted after truck assignment is confirmed."))

	if not interchange_document:
		frappe.throw(_("Interchange document is required."))

	interchange_date = getdate(interchange_date or today())

	_update_allocation_item_row(
		item_name,
		{
			"assignment_status": ASSIGNMENT_INTERCHANGE,
			"interchange_document": interchange_document,
			"interchange_date": interchange_date,
		},
	)

	tracker = frappe.get_doc("Container Tracker", item.container_tracker, ignore_permissions=True)
	tracker.interchange_document = interchange_document
	tracker.interchange_date = interchange_date
	tracker.save(ignore_permissions=True)

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
		after_tracker_interchange_updated,
	)

	interchange_task_completed = after_tracker_interchange_updated(tracker)
	allocation_completed = _maybe_complete_allocation(allocation_name)

	return {
		"ok": True,
		"assignment_status": ASSIGNMENT_INTERCHANGE,
		"interchange_task_completed": interchange_task_completed,
		"allocation_completed": allocation_completed,
		"message": _("Interchange submitted to CGM."),
	}


def save_interchange_draft(
	allocation_name: str,
	item_name: str,
	interchange_document: str,
	interchange_date: str | None = None,
) -> dict:
	"""Save interchange on the allocation row only — status stays Truck Assigned."""
	item = _get_allocation_item_row(allocation_name, item_name)

	if item.assignment_status != ASSIGNMENT_TRUCK:
		frappe.throw(_("Interchange can only be uploaded after truck assignment is confirmed."))

	if not (interchange_document or "").strip():
		frappe.throw(_("Interchange document is required."))

	values: dict[str, Any] = {"interchange_document": interchange_document.strip()}
	if interchange_date:
		values["interchange_date"] = getdate(interchange_date)
	else:
		values["interchange_date"] = today()

	_update_allocation_item_row(item_name, values)

	return {
		"ok": True,
		"assignment_status": ASSIGNMENT_TRUCK,
		"message": _("Interchange saved. Submit when ready to send to CGM."),
	}


def submit_interchange_from_item(
	allocation_name: str,
	item_name: str,
) -> dict:
	"""Submit saved interchange draft to CGM (Container Tracker)."""
	item = _get_allocation_item_row(allocation_name, item_name)

	if item.assignment_status != ASSIGNMENT_TRUCK:
		frappe.throw(_("Interchange has already been submitted or truck assignment is not confirmed."))

	draft = frappe.db.get_value(
		"Container Allocation Item",
		item_name,
		["interchange_document", "interchange_date"],
		as_dict=True,
	)
	if not draft or not (draft.interchange_document or "").strip():
		frappe.throw(_("Upload an interchange receipt before submitting."))

	return sync_interchange_from_item(
		allocation_name,
		item_name,
		draft.interchange_document,
		draft.interchange_date,
	)


def _get_allocation_item_row(allocation_name: str, item_name: str):
	allocation = frappe.get_doc("Container Allocation", allocation_name, ignore_permissions=True)
	return _get_allocation_item(allocation, item_name)


def acknowledge_allocation(allocation_name: str) -> None:
	allocation = frappe.get_doc("Container Allocation", allocation_name, ignore_permissions=True)
	if allocation.status == ALLOCATION_STATUS_ALLOCATED:
		allocation.db_set("status", ALLOCATION_STATUS_ACKNOWLEDGED, update_modified=True)


def _get_allocation_item(allocation, item_name: str):
	for row in allocation.containers or []:
		if row.name == item_name:
			return row
	frappe.throw(_("Container allocation row not found."), frappe.DoesNotExistError)


def _maybe_complete_allocation(allocation_name: str) -> bool:
	allocation = frappe.get_doc("Container Allocation", allocation_name)
	if not allocation.containers:
		return False
	if all(row.assignment_status == ASSIGNMENT_INTERCHANGE for row in allocation.containers):
		allocation.db_set("status", ALLOCATION_STATUS_COMPLETED, update_modified=True)
		return True
	return False
