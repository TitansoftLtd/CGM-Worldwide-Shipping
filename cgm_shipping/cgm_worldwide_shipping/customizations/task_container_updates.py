"""Task form → Container Tracker sync (tasks are the data-entry UI)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CONTAINER_UPDATE_TASK_SEQS,
	SEA_TASK_FLOW_KEY,
	TASK_CONTAINER_UPDATES_FIELD,
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


def _sea_task_seq(doc) -> int:
	return int(doc.get("custom_sequence_no") or 0)


def is_container_update_task(doc) -> bool:
	return (
		doc.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY
		and _sea_task_seq(doc) in CONTAINER_UPDATE_TASK_SEQS
	)


def seed_container_update_rows(doc) -> bool:
	"""Pre-fill custom_container_updates from project Container Trackers."""
	if doc.is_new() or not is_container_update_task(doc):
		return False
	if not doc.get("project"):
		return False
	if not doc.meta.has_field(TASK_CONTAINER_UPDATES_FIELD):
		return False

	existing = {
		row.container_tracker
		for row in doc.get(TASK_CONTAINER_UPDATES_FIELD) or []
		if row.get("container_tracker")
	}

	trackers = frappe.get_all(
		"Container Tracker",
		filters={"project": doc.project},
		fields=["name", "container_number", "type_of_container", "status"],
		order_by="container_number asc",
	)

	changed = False
	for tracker in trackers:
		if tracker.name in existing:
			continue
		doc.append(
			TASK_CONTAINER_UPDATES_FIELD,
			{
				"container_tracker": tracker.name,
				"container_number": tracker.container_number,
				"type_of_container": tracker.type_of_container,
				"current_status": tracker.status,
			},
		)
		changed = True
	return changed


def apply_container_updates_from_task(doc) -> None:
	"""Push task container grid rows to linked Container Trackers."""
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
	if seed_container_update_rows(doc):
		# Keep this strictly in-memory on load. Persist only on explicit user save
		# to avoid "modified after you opened it" conflicts.
		return
