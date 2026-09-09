# Copyright (c) 2026, Titansoft Limited and contributors
"""Container Allocation business logic and desk helpers."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime, today

from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	container_row_cargo_size,
	tracker_cargo_size_field,
)

ALLOCATION_STATUS_DRAFT = "Draft"
ALLOCATION_STATUS_ALLOCATED = "Allocated"
ALLOCATION_STATUS_ACKNOWLEDGED = "Acknowledged"
ALLOCATION_STATUS_COMPLETED = "Completed"

ASSIGNMENT_PENDING = "Pending"
ASSIGNMENT_TRUCK = "Truck Assigned"
ASSIGNMENT_INTERCHANGE = "Interchange Uploaded"

OFFERED_TRUCK_OFFERED = "Offered"
OFFERED_TRUCK_ASSIGNED = "Assigned"
OFFERED_TRUCK_WITHDRAWN = "Withdrawn"

CGM_ASSIGNMENT_ROLES = frozenset(
	{
		"System Manager",
		"Operations Manager",
		"Transport Officer",
	}
)

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
					"Move it to another transporter from that allocation, or complete the work there first."
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

	def _append_tracker(tracker: str, container_number: str = "", cargo_size: str = "") -> None:
		if not tracker or tracker in allocated or tracker in seen:
			return
		if not frappe.db.exists("Container Tracker", tracker):
			return
		size_field = tracker_cargo_size_field()
		tracker_values = frappe.db.get_value(
			"Container Tracker",
			tracker,
			["container_number", size_field],
			as_dict=True,
		) or {}
		containers.append(
			{
				"container_tracker": tracker,
				"container_number": container_number or tracker_values.get("container_number") or "",
				"cargo_size": cargo_size or tracker_values.get(size_field) or "",
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
			container_row_cargo_size(row),
		)

	size_field = tracker_cargo_size_field()
	for tracker_row in frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=["name", "container_number", size_field],
		order_by="container_number asc",
	):
		_append_tracker(
			tracker_row.name,
			tracker_row.container_number or "",
			tracker_row.get(size_field) or "",
		)

	return containers


@frappe.whitelist()
def get_container_allocation_defaults(project: str) -> dict:
	"""Pre-fill a new Container Allocation from a Project's unallocated containers."""
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	frappe.has_permission("Container Allocation", ptype="create", throw=True)

	project_doc = frappe.get_doc("Project", project)
	containers = build_unallocated_container_rows(project)
	return {
		"project": project,
		"bill_of_lading": project_doc.get("custom_bill_of_lading") or "",
		"allocation_date": today(),
		"allocated_by": frappe.session.user,
		"status": ALLOCATION_STATUS_DRAFT,
		"containers": containers,
		"remaining_count": len(containers),
	}


def _parse_tracker_list(container_trackers) -> list[str]:
	import json

	if isinstance(container_trackers, str):
		container_trackers = json.loads(container_trackers)
	if not isinstance(container_trackers, (list, tuple)):
		frappe.throw(_("Select at least one container."))
	out = []
	seen: set[str] = set()
	for raw in container_trackers:
		name = (raw or "").strip() if isinstance(raw, str) else str(raw or "").strip()
		if not name or name in seen:
			continue
		seen.add(name)
		out.append(name)
	if not out:
		frappe.throw(_("Select at least one container."))
	return out


def _assert_trackers_on_project(project: str, container_trackers: list[str]) -> list[dict]:
	"""Return Pending container row payloads; throws if tracker missing or wrong project."""
	rows: list[dict] = []
	size_field = tracker_cargo_size_field()
	for tracker in container_trackers:
		if not frappe.db.exists("Container Tracker", tracker):
			frappe.throw(_("Container Tracker {0} was not found.").format(frappe.bold(tracker)))
		values = frappe.db.get_value(
			"Container Tracker",
			tracker,
			["project", "container_number", size_field],
			as_dict=True,
		)
		if (values.get("project") or "") != project:
			frappe.throw(
				_("Container Tracker {0} does not belong to project {1}.").format(
					frappe.bold(tracker),
					frappe.bold(project),
				)
			)
		rows.append(
			{
				"container_tracker": tracker,
				"container_number": values.get("container_number") or "",
				"cargo_size": values.get(size_field) or "",
				"assignment_status": ASSIGNMENT_PENDING,
			}
		)
	return rows


def _assert_trackers_unallocated(container_trackers: list[str], exclude_allocation: str | None = None) -> None:
	for tracker in container_trackers:
		existing = get_active_allocation_for_tracker(tracker, exclude_allocation)
		if existing:
			frappe.throw(
				_(
					"Container Tracker {0} is already allocated on {1}. "
					"Move it from that allocation first."
				).format(frappe.bold(tracker), frappe.bold(existing))
			)


@frappe.whitelist()
def create_allocation_for_containers(
	project: str,
	transporter: str,
	container_trackers,
	trucks_booked: int | None = None,
	submit: int | bool = 1,
) -> dict:
	"""Create (and usually submit) a Container Allocation for a selected container subset."""
	frappe.has_permission("Container Allocation", ptype="create", throw=True)
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	assert_cgm_can_assign_trucks()

	if not project or not frappe.db.exists("Project", project):
		frappe.throw(_("Project is required."))
	if not (transporter or "").strip():
		frappe.throw(_("Select a transporter."))
	validate_transporter_supplier(transporter)

	trackers = _parse_tracker_list(container_trackers)
	_assert_trackers_unallocated(trackers)
	rows = _assert_trackers_on_project(project, trackers)

	booked = cint(trucks_booked) if trucks_booked is not None else len(rows)
	if booked <= 0:
		booked = len(rows)

	project_doc = frappe.get_doc("Project", project)
	doc = frappe.get_doc(
		{
			"doctype": "Container Allocation",
			"project": project,
			"bill_of_lading": project_doc.get("custom_bill_of_lading") or "",
			"transporter": transporter,
			"allocation_date": today(),
			"allocated_by": frappe.session.user,
			"trucks_booked": booked,
			"status": ALLOCATION_STATUS_DRAFT,
			"containers": rows,
		}
	)
	doc.insert(ignore_permissions=False)

	submitted = False
	if cint(submit):
		doc.submit()
		submitted = True

	return {
		"ok": True,
		"name": doc.name,
		"submitted": submitted,
		"trucks_booked": cint(doc.trucks_booked),
		"container_count": len(doc.containers or []),
		"message": (
			_("Allocation {0} created and submitted.").format(doc.name)
			if submitted
			else _("Allocation {0} created as draft.").format(doc.name)
		),
	}


@frappe.whitelist()
def get_project_allocations_for_move(project: str, exclude_allocation: str | None = None) -> list[dict]:
	"""Other active allocations on the same project (targets for move)."""
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	filters: dict[str, Any] = {
		"project": project,
		"docstatus": 1,
		"status": ("in", (ALLOCATION_STATUS_ALLOCATED, ALLOCATION_STATUS_ACKNOWLEDGED)),
	}
	if exclude_allocation:
		filters["name"] = ("!=", exclude_allocation)

	rows = frappe.get_all(
		"Container Allocation",
		filters=filters,
		fields=["name", "transporter", "status", "trucks_booked"],
		order_by="modified desc",
	)
	for row in rows:
		row["container_count"] = frappe.db.count(
			"Container Allocation Item", {"parent": row.name}
		)
		row["transporter_name"] = (
			frappe.db.get_value("Supplier", row.transporter, "supplier_name") or row.transporter
		)
	return rows


def _delete_allocation_item(item_name: str) -> None:
	frappe.db.delete("Container Allocation Item", {"name": item_name})


def _append_pending_container_to_allocation(allocation_name: str, row: dict) -> str:
	"""Append a Pending container child to a submitted allocation; returns child name."""
	allocation = frappe.get_doc("Container Allocation", allocation_name, ignore_permissions=True)
	child = allocation.append(
		"containers",
		{
			"container_tracker": row["container_tracker"],
			"container_number": row.get("container_number") or "",
			"cargo_size": row.get("cargo_size") or "",
			"assignment_status": ASSIGNMENT_PENDING,
			"offered_truck": None,
			"truck_number": "",
			"driver_name": "",
			"driver_contact": "",
			"interchange_document": "",
			"interchange_date": None,
		},
	)
	allocation.flags.ignore_permissions = True
	allocation.flags.ignore_validate_update_after_submit = True
	allocation.save()
	return child.name


def _clear_item_truck_assignment(allocation_name: str, item) -> None:
	"""Clear truck assignment before moving; refresh offered truck availability."""
	previous_truck = getattr(item, "offered_truck", None)
	if item.assignment_status == ASSIGNMENT_INTERCHANGE:
		frappe.throw(
			_(
				"Container {0} already has interchange uploaded and cannot be moved."
			).format(frappe.bold(item.container_number or item.container_tracker))
		)

	if item.assignment_status == ASSIGNMENT_TRUCK or previous_truck or item.truck_number:
		_update_allocation_item_row(
			item.name,
			{
				"offered_truck": None,
				"truck_number": "",
				"driver_name": "",
				"driver_contact": "",
				"assignment_status": ASSIGNMENT_PENDING,
			},
		)
		if item.container_tracker:
			_sync_tracker_truck_details(item.container_tracker, "", "", "")
		_refresh_offered_truck_status(allocation_name, previous_truck)


@frappe.whitelist()
def reallocate_containers(
	source_allocation: str,
	container_trackers,
	reason: str,
	target_allocation: str | None = None,
	transporter: str | None = None,
	trucks_booked: int | None = None,
) -> dict:
	"""
	Move containers from Allocation A to Allocation B (or a new allocation) without cancelling A.
	"""
	frappe.has_permission("Container Allocation", ptype="write", doc=source_allocation, throw=True)
	assert_cgm_can_assign_trucks()

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Enter a reason for moving these containers."))

	trackers = _parse_tracker_list(container_trackers)
	source = frappe.get_doc("Container Allocation", source_allocation, ignore_permissions=True)
	if source.docstatus != 1:
		frappe.throw(_("Move containers only from a submitted allocation."))
	if source.status == ALLOCATION_STATUS_COMPLETED:
		frappe.throw(_("Completed allocations cannot be changed."))

	source_items_by_tracker = {
		row.container_tracker: row for row in (source.containers or []) if row.container_tracker
	}
	missing = [t for t in trackers if t not in source_items_by_tracker]
	if missing:
		frappe.throw(
			_("Container(s) {0} are not on allocation {1}.").format(
				frappe.bold(", ".join(missing)),
				frappe.bold(source_allocation),
			)
		)

	target_name = (target_allocation or "").strip() or None
	new_transporter = (transporter or "").strip() or None

	if target_name and new_transporter:
		frappe.throw(_("Choose either an existing allocation or a new transporter, not both."))
	if not target_name and not new_transporter:
		frappe.throw(_("Select a target allocation or a new transporter."))

	moved_labels: list[str] = []
	for tracker in trackers:
		item = source_items_by_tracker[tracker]
		_clear_item_truck_assignment(source_allocation, item)
		# Reload item fields after clear
		item = frappe.get_doc("Container Allocation Item", item.name)
		moved_labels.append(item.container_number or tracker)
		_delete_allocation_item(item.name)

	frappe.clear_document_cache("Container Allocation", source_allocation)

	created_new = False
	if target_name:
		target = frappe.get_doc("Container Allocation", target_name, ignore_permissions=True)
		if target.name == source_allocation:
			frappe.throw(_("Choose a different target allocation."))
		if target.project != source.project:
			frappe.throw(_("Target allocation must be on the same project."))
		if target.docstatus != 1:
			frappe.throw(_("Target allocation must be submitted."))
		if target.status == ALLOCATION_STATUS_COMPLETED:
			frappe.throw(_("Target allocation is completed."))
		frappe.has_permission("Container Allocation", ptype="write", doc=target_name, throw=True)

		_assert_trackers_unallocated(trackers, exclude_allocation=source_allocation)
		row_payloads = _assert_trackers_on_project(source.project, trackers)
		for row in row_payloads:
			_append_pending_container_to_allocation(target_name, row)
			frappe.db.set_value(
				"Container Tracker",
				row["container_tracker"],
				"transporter",
				target.transporter,
				update_modified=True,
			)
			frappe.clear_document_cache("Container Tracker", row["container_tracker"])
	else:
		validate_transporter_supplier(new_transporter)
		# Trackers were removed from source; they are free for a new allocation.
		result = create_allocation_for_containers(
			project=source.project,
			transporter=new_transporter,
			container_trackers=trackers,
			trucks_booked=cint(trucks_booked) if trucks_booked is not None else len(trackers),
			submit=1,
		)
		target_name = result["name"]
		created_new = True

	label_list = ", ".join(moved_labels)
	_add_assignment_comment(
		source_allocation,
		_("Moved container(s) {0} to {1}. Reason: {2}").format(
			label_list, target_name, reason
		),
	)
	_add_assignment_comment(
		target_name,
		_("Received container(s) {0} from {1}. Reason: {2}").format(
			label_list, source_allocation, reason
		),
	)

	remaining = frappe.db.count("Container Allocation Item", {"parent": source_allocation})
	if remaining == 0:
		_add_assignment_comment(
			source_allocation,
			_("All containers were moved to other allocations. This allocation is kept for records."),
		)

	return {
		"ok": True,
		"source_allocation": source_allocation,
		"target_allocation": target_name,
		"created_new": created_new,
		"moved": len(trackers),
		"source_remaining": remaining,
		"message": _("Moved {0} container(s) to {1}.").format(len(trackers), target_name),
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


def assert_cgm_can_assign_trucks() -> None:
	"""Desk roles that may assign / reassign containers to offered trucks."""
	if frappe.session.user == "Administrator":
		return
	if set(frappe.get_roles()).intersection(CGM_ASSIGNMENT_ROLES):
		return
	frappe.throw(
		_("Only CGM transport or operations users can assign containers to trucks."),
		frappe.PermissionError,
	)


def _normalize_truck_offer_row(row: dict | None) -> dict:
	row = row or {}
	truck_number = (row.get("truck_number") or "").strip()
	driver_name = (row.get("driver_name") or "").strip()
	driver_contact = (row.get("driver_contact") or "").strip()
	if not truck_number:
		frappe.throw(_("Each offered truck needs a truck number."))
	if not driver_name:
		frappe.throw(_("Each offered truck needs a driver name."))
	return {
		"truck_number": truck_number,
		"driver_name": driver_name,
		"driver_contact": driver_contact,
	}


def _get_offered_truck(allocation, offered_truck_name: str):
	for row in allocation.get("offered_trucks") or []:
		if row.name == offered_truck_name:
			return row
	frappe.throw(_("Offered truck not found on this allocation."), frappe.DoesNotExistError)


def _container_using_offered_truck(
	allocation, offered_truck_name: str, exclude_item: str | None = None
):
	for row in allocation.containers or []:
		if row.name == exclude_item:
			continue
		if (row.offered_truck or "") != offered_truck_name:
			continue
		if row.assignment_status in (ASSIGNMENT_TRUCK, ASSIGNMENT_INTERCHANGE):
			return row
	return None


def _refresh_offered_truck_status(allocation_name: str, offered_truck_name: str | None) -> None:
	if not offered_truck_name:
		return
	allocation = frappe.get_doc("Container Allocation", allocation_name, ignore_permissions=True)
	truck = _get_offered_truck(allocation, offered_truck_name)
	if truck.status == OFFERED_TRUCK_WITHDRAWN:
		return
	in_use = _container_using_offered_truck(allocation, offered_truck_name)
	new_status = OFFERED_TRUCK_ASSIGNED if in_use else OFFERED_TRUCK_OFFERED
	if truck.status != new_status:
		frappe.db.set_value(
			"Container Allocation Truck",
			offered_truck_name,
			"status",
			new_status,
			update_modified=False,
		)


def _sync_tracker_truck_details(
	container_tracker: str, truck_number: str, driver_name: str, driver_contact: str
) -> None:
	tracker = frappe.get_doc("Container Tracker", container_tracker, ignore_permissions=True)
	tracker.truck_number = truck_number
	tracker.driver_name = driver_name
	tracker.driver_contact = driver_contact
	tracker.save(ignore_permissions=True)


def _add_assignment_comment(allocation_name: str, message: str) -> None:
	frappe.get_doc("Container Allocation", allocation_name).add_comment("Info", message)


def submit_offered_trucks(allocation_name: str, trucks) -> dict:
	"""Append one or more trucks offered by the transporter (batch-friendly)."""
	import json

	if isinstance(trucks, str):
		trucks = json.loads(trucks)
	if not isinstance(trucks, list) or not trucks:
		frappe.throw(_("Add at least one truck with driver details."))

	allocation = frappe.get_doc("Container Allocation", allocation_name, ignore_permissions=True)
	if allocation.docstatus != 1:
		frappe.throw(_("Offer trucks only on a submitted allocation."))
	if allocation.status == ALLOCATION_STATUS_COMPLETED:
		frappe.throw(_("This allocation is completed. New trucks cannot be offered."))

	normalized = [_normalize_truck_offer_row(row) for row in trucks]
	existing_keys = {
		((row.truck_number or "").strip().upper(), (row.driver_name or "").strip().upper())
		for row in allocation.get("offered_trucks") or []
		if row.status != OFFERED_TRUCK_WITHDRAWN
	}

	added = []
	now = now_datetime()
	for row in normalized:
		key = (row["truck_number"].upper(), row["driver_name"].upper())
		if key in existing_keys:
			frappe.throw(
				_("Truck {0} with driver {1} is already offered on this allocation.").format(
					frappe.bold(row["truck_number"]),
					frappe.bold(row["driver_name"]),
				)
			)
		existing_keys.add(key)
		child = allocation.append(
			"offered_trucks",
			{
				"truck_number": row["truck_number"],
				"driver_name": row["driver_name"],
				"driver_contact": row["driver_contact"],
				"status": OFFERED_TRUCK_OFFERED,
				"offered_on": now,
				"offered_by": frappe.session.user,
			},
		)
		added.append(child)

	allocation.flags.ignore_permissions = True
	allocation.flags.ignore_validate_update_after_submit = True
	allocation.save()

	if allocation.status == ALLOCATION_STATUS_ALLOCATED:
		acknowledge_allocation(allocation_name)

	return {
		"ok": True,
		"added": len(added),
		"offered_truck_names": [row.name for row in added],
		"message": _("Offered {0} truck(s). CGM will assign containers.").format(len(added)),
	}


def withdraw_offered_truck(allocation_name: str, offered_truck_name: str) -> dict:
	"""Transporter may withdraw a truck that CGM has not assigned yet."""
	allocation = frappe.get_doc("Container Allocation", allocation_name, ignore_permissions=True)
	if allocation.status == ALLOCATION_STATUS_COMPLETED:
		frappe.throw(_("Completed allocations cannot be changed."))

	truck = _get_offered_truck(allocation, offered_truck_name)
	if truck.status == OFFERED_TRUCK_WITHDRAWN:
		return {"ok": True, "status": OFFERED_TRUCK_WITHDRAWN}

	if _container_using_offered_truck(allocation, offered_truck_name):
		frappe.throw(
			_("Truck {0} is already assigned to a container. Ask CGM to reassign first.").format(
				frappe.bold(truck.truck_number)
			)
		)

	frappe.db.set_value(
		"Container Allocation Truck",
		offered_truck_name,
		"status",
		OFFERED_TRUCK_WITHDRAWN,
		update_modified=False,
	)
	_add_assignment_comment(
		allocation_name,
		_("Withdrawn offered truck {0} ({1}).").format(truck.truck_number, truck.driver_name),
	)
	return {"ok": True, "status": OFFERED_TRUCK_WITHDRAWN}


def assign_container_to_offered_truck(
	allocation_name: str,
	item_name: str,
	offered_truck_name: str,
	reason: str = "",
	*,
	is_reassignment: bool = False,
) -> dict:
	"""CGM assigns (or reassigns) a container to a transporter-offered truck."""
	assert_cgm_can_assign_trucks()

	allocation = frappe.get_doc("Container Allocation", allocation_name, ignore_permissions=True)
	if allocation.docstatus != 1:
		frappe.throw(_("Assign trucks only on a submitted allocation."))
	if allocation.status == ALLOCATION_STATUS_COMPLETED:
		frappe.throw(_("This allocation is completed."))

	item = _get_allocation_item(allocation, item_name)
	truck = _get_offered_truck(allocation, offered_truck_name)

	if truck.status == OFFERED_TRUCK_WITHDRAWN:
		frappe.throw(_("Cannot assign a withdrawn truck."))

	if item.assignment_status == ASSIGNMENT_INTERCHANGE:
		frappe.throw(_("Cannot reassign after interchange has been uploaded."))

	if is_reassignment:
		if item.assignment_status != ASSIGNMENT_TRUCK:
			frappe.throw(_("Reassign only after a container already has a truck assigned."))
		if not (reason or "").strip():
			frappe.throw(_("Enter a reason for the reassignment."))
	elif item.assignment_status == ASSIGNMENT_TRUCK:
		frappe.throw(_("This container already has a truck. Use Reassign instead."))

	conflict = _container_using_offered_truck(
		allocation, offered_truck_name, exclude_item=item_name
	)
	if conflict:
		frappe.throw(
			_("Truck {0} is already assigned to container {1}.").format(
				frappe.bold(truck.truck_number),
				frappe.bold(conflict.container_number or conflict.container_tracker),
			)
		)

	previous_truck = item.offered_truck
	previous_truck_number = item.truck_number

	_update_allocation_item_row(
		item_name,
		{
			"offered_truck": offered_truck_name,
			"truck_number": truck.truck_number,
			"driver_name": truck.driver_name,
			"driver_contact": truck.driver_contact or "",
			"assignment_status": ASSIGNMENT_TRUCK,
		},
	)
	_sync_tracker_truck_details(
		item.container_tracker,
		truck.truck_number,
		truck.driver_name,
		truck.driver_contact or "",
	)

	_refresh_offered_truck_status(allocation_name, previous_truck)
	_refresh_offered_truck_status(allocation_name, offered_truck_name)

	container_label = item.container_number or item.container_tracker
	if is_reassignment:
		_add_assignment_comment(
			allocation_name,
			_(
				"Reassigned container {0} from truck {1} to truck {2}. Reason: {3}"
			).format(
				container_label,
				previous_truck_number or previous_truck or "—",
				truck.truck_number,
				(reason or "").strip(),
			),
		)
		message = _("Container reassigned to truck {0}.").format(truck.truck_number)
	else:
		_add_assignment_comment(
			allocation_name,
			_("Assigned container {0} to truck {1} ({2}).").format(
				container_label, truck.truck_number, truck.driver_name
			),
		)
		message = _("Container assigned to truck {0}.").format(truck.truck_number)

	return {
		"ok": True,
		"assignment_status": ASSIGNMENT_TRUCK,
		"truck_number": truck.truck_number,
		"driver_name": truck.driver_name,
		"driver_contact": truck.driver_contact or "",
		"offered_truck": offered_truck_name,
		"message": message,
	}


def reassign_container_to_offered_truck(
	allocation_name: str,
	item_name: str,
	offered_truck_name: str,
	reason: str,
) -> dict:
	"""CGM-only reassignment wrapper (reason required)."""
	return assign_container_to_offered_truck(
		allocation_name,
		item_name,
		offered_truck_name,
		reason=reason,
		is_reassignment=True,
	)


@frappe.whitelist()
def get_assignment_board(allocation_name: str) -> dict:
	"""Payload for the CGM assign / reassign dialog."""
	frappe.has_permission("Container Allocation", ptype="write", doc=allocation_name, throw=True)
	assert_cgm_can_assign_trucks()

	allocation = frappe.get_doc("Container Allocation", allocation_name)
	pending = []
	assigned = []
	for row in allocation.containers or []:
		payload = {
			"name": row.name,
			"container_tracker": row.container_tracker,
			"container_number": row.container_number,
			"cargo_size": row.cargo_size,
			"assignment_status": row.assignment_status or ASSIGNMENT_PENDING,
			"offered_truck": row.offered_truck,
			"truck_number": row.truck_number,
			"driver_name": row.driver_name,
			"driver_contact": row.driver_contact,
		}
		if row.assignment_status == ASSIGNMENT_PENDING:
			pending.append(payload)
		elif row.assignment_status == ASSIGNMENT_TRUCK:
			assigned.append(payload)

	available_trucks = []
	for truck in allocation.get("offered_trucks") or []:
		if truck.status == OFFERED_TRUCK_WITHDRAWN:
			continue
		in_use = _container_using_offered_truck(allocation, truck.name)
		available_trucks.append(
			{
				"name": truck.name,
				"truck_number": truck.truck_number,
				"driver_name": truck.driver_name,
				"driver_contact": truck.driver_contact,
				"status": truck.status,
				"available": not bool(in_use),
				"assigned_container": (
					in_use.container_number or in_use.container_tracker if in_use else ""
				),
			}
		)

	return {
		"allocation": allocation_name,
		"pending_containers": pending,
		"assigned_containers": assigned,
		"offered_trucks": available_trucks,
		"trucks_booked": cint(allocation.trucks_booked),
	}


@frappe.whitelist()
def assign_container_to_truck(
	allocation_name: str,
	item_name: str,
	offered_truck_name: str,
) -> dict:
	"""Whitelisted CGM assign action."""
	frappe.has_permission("Container Allocation", ptype="write", doc=allocation_name, throw=True)
	return assign_container_to_offered_truck(
		allocation_name, item_name, offered_truck_name, is_reassignment=False
	)


@frappe.whitelist()
def reassign_container_truck(
	allocation_name: str,
	item_name: str,
	offered_truck_name: str,
	reason: str,
) -> dict:
	"""Whitelisted CGM reassign action."""
	frappe.has_permission("Container Allocation", ptype="write", doc=allocation_name, throw=True)
	return reassign_container_to_offered_truck(
		allocation_name, item_name, offered_truck_name, reason
	)


def save_assignment_draft(
	allocation_name: str,
	item_name: str,
	truck_number: str,
	driver_name: str,
	driver_contact: str = "",
) -> dict:
	"""Legacy path — transporters now offer trucks in batch; CGM assigns containers."""
	frappe.throw(
		_(
			"Truck details are offered in the Offered Trucks list. "
			"CGM assigns each container to an offered truck."
		),
		title=_("Use Offered Trucks"),
	)


def submit_truck_assignment(
	allocation_name: str,
	item_name: str,
	truck_number: str,
	driver_name: str,
	driver_contact: str = "",
) -> dict:
	"""Legacy alias kept for older callers — prefer assign_container_to_offered_truck."""
	frappe.throw(
		_(
			"Truck assignment is done by CGM from Offered Trucks. "
			"Ask the transporter to offer trucks, then use Assign Containers to Trucks."
		),
		title=_("Use Offered Trucks"),
	)


def sync_truck_assignment_from_item(
	allocation_name: str,
	item_name: str,
	truck_number: str,
	driver_name: str,
	driver_contact: str,
) -> dict:
	"""Backward-compatible alias — redirected to the offered-truck flow."""
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
