"""Task form → Container Tracker sync (tasks are the data-entry UI)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CONTAINER_UPDATE_TASK_SEQS,
	SEA_TASK_FLOW_KEY,
	TASK_CONTAINER_UPDATES_FIELD,
	TRANSPORT_TASK_SEQS,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	get_container_task_sequence,
)

# Task Container Update row field → Container Tracker field
SEQ_FIELD_MAP: dict[int, list[tuple[str, str]]] = {
	11: [("discharging_date", "discharging_date")],
	16: [("verification_location", "current_location")],
	18: [
		("free_days_start_date", "free_days_start_date"),
		("free_days_end_date", "free_days_end_date"),
		("demurrage_daily_rate", "demurrage_daily_rate"),
		("kpa_daily_rate", "kpa_daily_rate"),
		("kpa_free_days_override", "kpa_free_days"),
	],
	19: [
		("transporter", "transporter"),
		("truck_number", "truck_number"),
		("driver_name", "driver_name"),
		("driver_contact", "driver_contact"),
	],
	20: [("gate_out_date_port", "gate_out_date_port")],
	21: [
		("gate_in_date_warehouse", "gate_in_date_warehouse"),
		("delivery_location", "delivery_location"),
	],
	22: [
		("offloading_date", "offloading_date"),
		("container_emptied_location", "delivery_location"),
	],
	23: [
		("actual_empty_return", "actual_empty_return"),
		("gate_in_date_depot", "gate_in_date_depot"),
	],
	24: [
		("interchange_date", "interchange_date"),
		("interchange_document", "interchange_document"),
	],
}

COMPLETION_FIELD_BY_SEQ: dict[int, str] = {
	19: "truck_number",
	20: "gate_out_date_port",
	21: "gate_in_date_warehouse",
	22: "offloading_date",
	23: "actual_empty_return",
	24: "interchange_date",
}

TRACKER_SEED_FIELDS = [
	"name",
	"container_number",
	"type_of_container",
	"status",
	"truck_number",
	"driver_name",
	"driver_contact",
	"transporter",
	"gate_out_date_port",
	"offloading_date",
	"actual_empty_return",
	"interchange_date",
	"gate_in_date_warehouse",
	"delivery_location",
]


def _sea_task_seq(doc) -> int:
	return int(doc.get("custom_sequence_no") or 0)


def is_container_update_task(doc) -> bool:
	return (
		doc.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY
		and _sea_task_seq(doc) in CONTAINER_UPDATE_TASK_SEQS
	)


def _prefill_row_from_tracker(row, tracker: dict, seq: int) -> bool:
	changed = False
	if row.current_status != tracker.get("status"):
		row.current_status = tracker.get("status")
		changed = True

	if seq == 19:
		for field in ("truck_number", "driver_name", "driver_contact", "transporter"):
			if not row.get(field) and tracker.get(field):
				row.set(field, tracker.get(field))
				changed = True
	elif seq == 20 and not row.get("gate_out_date_port") and tracker.get("gate_out_date_port"):
		row.gate_out_date_port = tracker.get("gate_out_date_port")
		changed = True
	elif seq == 21:
		for field in ("gate_in_date_warehouse", "delivery_location"):
			if not row.get(field) and tracker.get(field):
				row.set(field, tracker.get(field))
				changed = True
	elif seq == 22 and not row.get("offloading_date") and tracker.get("offloading_date"):
		row.offloading_date = tracker.get("offloading_date")
		changed = True
	elif seq == 23 and not row.get("actual_empty_return") and tracker.get("actual_empty_return"):
		row.actual_empty_return = tracker.get("actual_empty_return")
		changed = True
	elif seq == 24 and not row.get("interchange_date") and tracker.get("interchange_date"):
		row.interchange_date = tracker.get("interchange_date")
		changed = True
	return changed


def seed_container_update_rows(doc) -> bool:
	"""Pre-fill custom_container_updates from live Container Tracker data."""
	if doc.is_new() or not is_container_update_task(doc):
		return False
	if not doc.get("project"):
		return False
	if not doc.meta.has_field(TASK_CONTAINER_UPDATES_FIELD):
		return False

	seq = _sea_task_seq(doc)
	existing = {
		row.container_tracker: row
		for row in doc.get(TASK_CONTAINER_UPDATES_FIELD) or []
		if row.get("container_tracker")
	}

	trackers = frappe.get_all(
		"Container Tracker",
		filters={"project": doc.project},
		fields=TRACKER_SEED_FIELDS,
		order_by="container_number asc",
	)

	changed = False
	for tracker in trackers:
		if tracker.name in existing:
			if _prefill_row_from_tracker(existing[tracker.name], tracker, seq):
				changed = True
			continue

		row_data = {
			"container_tracker": tracker.name,
			"container_number": tracker.container_number,
			"type_of_container": tracker.type_of_container,
			"current_status": tracker.status,
		}
		if seq == 19:
			row_data.update(
				{
					"truck_number": tracker.truck_number or "",
					"driver_name": tracker.driver_name or "",
					"driver_contact": tracker.driver_contact or "",
					"transporter": tracker.transporter or "",
				}
			)
		elif seq == 21:
			row_data.update(
				{
					"gate_in_date_warehouse": tracker.gate_in_date_warehouse,
					"delivery_location": tracker.delivery_location or "",
				}
			)

		doc.append(TASK_CONTAINER_UPDATES_FIELD, row_data)
		changed = True
	return changed


def apply_container_updates_from_task(doc) -> None:
	"""Push filled task container grid rows to linked Container Trackers (partial saves OK)."""
	if not is_container_update_task(doc):
		return
	if not doc.meta.has_field(TASK_CONTAINER_UPDATES_FIELD):
		return

	seq = _sea_task_seq(doc)
	field_pairs = SEQ_FIELD_MAP.get(seq, [])
	if not field_pairs:
		return

	for row in doc.get(TASK_CONTAINER_UPDATES_FIELD) or []:
		tracker_name = row.get("container_tracker")
		if not tracker_name or not frappe.db.exists("Container Tracker", tracker_name):
			continue

		updates: dict[str, Any] = {}
		for task_field, tracker_field in field_pairs:
			val = row.get(task_field)
			if val is not None and val != "":
				updates[tracker_field] = val

		if not updates:
			continue

		ct = frappe.get_doc("Container Tracker", tracker_name)
		if ct.project != doc.project:
			frappe.throw(
				_("Container {0} does not belong to project {1}.").format(
					tracker_name, doc.project
				)
			)
		for field, value in updates.items():
			ct.set(field, value)
		ct.save(ignore_permissions=True)


def check_task_container_completion(doc) -> None:
	"""Auto-complete transport tasks when every project container satisfies the step."""
	if doc.status == "Completed":
		return
	if not doc.get("project"):
		return

	seq = _sea_task_seq(doc)
	check_field = COMPLETION_FIELD_BY_SEQ.get(seq)
	if not check_field:
		return

	trackers = frappe.get_all(
		"Container Tracker",
		filters={"project": doc.project},
		fields=["name", "container_number", check_field],
	)
	if not trackers:
		return

	if not all(t.get(check_field) for t in trackers):
		return

	frappe.db.set_value(
		"Task",
		doc.name,
		{
			"status": "Completed",
			"completed_by": frappe.session.user,
			"completed_on": now_datetime(),
		},
		update_modified=True,
	)
	frappe.clear_document_cache("Task", doc.name)

	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		sync_project_shipment_status_from_tasks,
	)

	sync_project_shipment_status_from_tasks(doc.project)
	frappe.publish_realtime(
		"cgm_project_tracking_refresh",
		{"project": doc.project},
		doctype="Project",
		docname=doc.project,
	)


def validate_task_19_container_updates(doc) -> None:
	"""Task 19: truck details for at least one container OR task-level reason."""
	if doc.get("custom_task_flow_key") != SEA_TASK_FLOW_KEY:
		return
	if _sea_task_seq(doc) != get_container_task_sequence("custom_book_trucks_task_seq"):
		return
	if doc.status != "Completed":
		return

	prev = doc.get_doc_before_save()
	if prev and prev.status == "Completed":
		return

	if not doc.meta.has_field(TASK_CONTAINER_UPDATES_FIELD):
		return

	rows = doc.get(TASK_CONTAINER_UPDATES_FIELD) or []
	has_truck = any((row.get("truck_number") or "").strip() for row in rows)
	has_reason = bool((doc.get("custom_not_emptied_reason") or "").strip())

	if not has_truck and not has_reason:
		frappe.throw(
			_(
				"Fill truck details for at least one container, or provide a reason "
				"why containers are not exiting port."
			)
		)


def on_task_onload_container_updates(doc) -> None:
	if doc.is_new():
		return
	seed_container_update_rows(doc)
