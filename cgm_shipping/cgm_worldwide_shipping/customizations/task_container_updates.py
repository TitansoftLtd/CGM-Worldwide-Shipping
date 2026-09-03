"""Task form ↔ Container Tracker sync (tasks are the data-entry UI)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CONTAINER_UPDATE_TASK_SEQS,
	TASK_CONTAINER_UPDATES_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	get_container_task_sequence,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	tracker_cargo_size_field,
	tracker_row_cargo_size,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	is_sea_import_task,
	task_flow_key_in_filter,
)

TRACKER_TO_TASK_FIELDS = (
	"transporter",
	"truck_number",
	"driver_name",
	"driver_contact",
	"free_days_start_date",
	"free_days_end_date",
	"kpa_free_days_start_date",
	"kpa_free_days_end_date",
	"gate_out_date_port",
	"gate_in_date_warehouse",
	"delivery_location",
	"offloading_date",
	"actual_empty_return",
	"interchange_date",
)

TRANSPORT_TRACKER_FIELDS = (
	"transporter",
	"truck_number",
	"driver_name",
	"driver_contact",
)


def _seq_field_map() -> dict[int, list[tuple[str, str]]]:
	"""Task grid field → Container Tracker field, keyed by configured sequence number."""
	mapping: dict[int, list[tuple[str, str]]] = {
		get_container_task_sequence("custom_vessel_arrival_task_seq"): [
			("discharging_date", "discharging_date"),
		],
		get_container_task_sequence("custom_field_clearance_task_seq"): [
			("verification_location", "current_location"),
		],
		get_container_task_sequence("custom_book_trucks_task_seq"): [
			("transporter", "transporter"),
			("truck_number", "truck_number"),
			("driver_name", "driver_name"),
			("driver_contact", "driver_contact"),
		],
		get_container_task_sequence("custom_gate_out_task_seq"): [
			("gate_out_date_port", "gate_out_date_port"),
			("free_days_start_date", "free_days_start_date"),
			("free_days_end_date", "free_days_end_date"),
			("kpa_free_days_start_date", "kpa_free_days_start_date"),
			("kpa_free_days_end_date", "kpa_free_days_end_date"),
		],
		get_container_task_sequence("custom_monitor_delivery_task_seq"): [
			("gate_in_date_warehouse", "gate_in_date_warehouse"),
			("delivery_location", "delivery_location"),
		],
		get_container_task_sequence("custom_offload_task_seq"): [
			("offloading_date", "offloading_date"),
			("container_emptied_location", "delivery_location"),
		],
		get_container_task_sequence("custom_empty_return_task_seq"): [
			("actual_empty_return", "actual_empty_return"),
			("gate_in_date_depot", "gate_in_date_depot"),
		],
		get_container_task_sequence("custom_interchange_task_seq"): [
			("interchange_date", "interchange_date"),
			("interchange_document", "interchange_document"),
		],
	}
	# Shipping Line Application: deposit fields are mirrored from Bill of Lading (read-only).
	# Do not map them onto Container Tracker.
	return mapping


def _shipping_line_application_seqs() -> frozenset[int]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		shipping_line_application_sequences,
	)

	return shipping_line_application_sequences()


def _shipping_line_finance_seqs() -> frozenset[int]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		shipping_line_finance_payment_sequences,
	)

	return shipping_line_finance_payment_sequences()


def is_shipping_line_deposit_task(doc) -> bool:
	return (
		is_sea_import_task(doc)
		and _sea_task_seq(doc) in _shipping_line_application_seqs()
	)


def is_shipping_line_deposit_mirror_task(doc) -> bool:
	"""Shipping Line Application or Finance payment tasks that mirror BL deposit fields."""
	if not is_sea_import_task(doc):
		return False
	seq = _sea_task_seq(doc)
	return seq in _shipping_line_application_seqs() or seq in _shipping_line_finance_seqs()


def _completion_field_by_seq() -> dict[int, str]:
	return {
		get_container_task_sequence("custom_book_trucks_task_seq"): "truck_number",
		get_container_task_sequence("custom_gate_out_task_seq"): "gate_out_date_port",
		get_container_task_sequence("custom_monitor_delivery_task_seq"): "gate_in_date_warehouse",
		get_container_task_sequence("custom_offload_task_seq"): "offloading_date",
		get_container_task_sequence("custom_empty_return_task_seq"): "actual_empty_return",
		get_container_task_sequence("custom_interchange_task_seq"): "interchange_date",
	}


def _trackers_missing_field(project: str, field: str) -> list[str]:
	trackers = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=["name", "container_number", field],
	)
	return [
		t.container_number or t.name
		for t in trackers
		if not t.get(field)
	]


def _trackers_missing_interchange(project: str) -> list[str]:
	"""Containers on the project still missing interchange date or receipt."""
	trackers = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=["name", "container_number", "interchange_date", "interchange_document"],
	)
	return [
		t.container_number or t.name
		for t in trackers
		if not t.get("interchange_date") or not (t.get("interchange_document") or "").strip()
	]


def _containers_missing_step(project: str, seq: int) -> list[str]:
	interchange_seq = get_container_task_sequence("custom_interchange_task_seq")
	if seq == interchange_seq:
		return _trackers_missing_interchange(project)
	check_field = _completion_field_by_seq().get(seq)
	if not check_field:
		return []
	return _trackers_missing_field(project, check_field)


TRACKER_SEED_FIELDS = [
	"name",
	"container_number",
	tracker_cargo_size_field(),
	"status",
	"ata",
	"discharging_date",
	"truck_number",
	"driver_name",
	"driver_contact",
	"transporter",
	"gate_out_date_port",
	"free_days_start_date",
	"free_days_end_date",
	"kpa_free_days_start_date",
	"kpa_free_days_end_date",
	"offloading_date",
	"actual_empty_return",
	"interchange_date",
	"interchange_document",
	"gate_in_date_warehouse",
	"delivery_location",
]


def _sea_task_seq(doc) -> int:
	return int(doc.get("custom_sequence_no") or 0)


def is_container_update_task(doc) -> bool:
	if not is_sea_import_task(doc):
		return False
	seq = _sea_task_seq(doc)
	return (
		seq in CONTAINER_UPDATE_TASK_SEQS
		or seq in _shipping_line_application_seqs()
		or seq in _shipping_line_finance_seqs()
	)


def _prefill_row_from_tracker(row, tracker: dict, seq: int, project: str | None = None) -> bool:
	changed = False
	if row.current_status != tracker.get("status"):
		row.current_status = tracker.get("status")
		changed = True

	book_seq = get_container_task_sequence("custom_book_trucks_task_seq")
	gate_out_seq = get_container_task_sequence("custom_gate_out_task_seq")
	monitor_seq = get_container_task_sequence("custom_monitor_delivery_task_seq")
	offload_seq = get_container_task_sequence("custom_offload_task_seq")
	empty_seq = get_container_task_sequence("custom_empty_return_task_seq")
	interchange_seq = get_container_task_sequence("custom_interchange_task_seq")
	vessel_arrival_seq = get_container_task_sequence("custom_vessel_arrival_task_seq")

	if seq == vessel_arrival_seq:
		# Project confirm is the source of truth — keep grid in sync with trackers.
		discharge = tracker.get("discharging_date") or tracker.get("ata")
		if discharge and row.get("discharging_date") != discharge:
			row.discharging_date = discharge
			changed = True
	elif seq in _shipping_line_application_seqs() or seq in _shipping_line_finance_seqs():
		bl_map = _bl_deposit_by_container_number(project or tracker.get("project") or "")
		src = bl_map.get((tracker.get("container_number") or "").strip().upper()) or {}
		new_amt = flt(src.get("deposit_amount"))
		if flt(row.get("deposit_amount")) != new_amt:
			row.deposit_amount = new_amt
			changed = True
	elif seq == book_seq:
		for field in TRANSPORT_TRACKER_FIELDS:
			if not row.get(field) and tracker.get(field):
				row.set(field, tracker.get(field))
				changed = True
	elif seq == gate_out_seq:
		for field in (
			"gate_out_date_port",
			"free_days_start_date",
			"free_days_end_date",
			"kpa_free_days_start_date",
			"kpa_free_days_end_date",
		):
			if not row.get(field) and tracker.get(field):
				row.set(field, tracker.get(field))
				changed = True
	elif seq == monitor_seq:
		for field in ("gate_in_date_warehouse", "delivery_location"):
			if not row.get(field) and tracker.get(field):
				row.set(field, tracker.get(field))
				changed = True
	elif seq == offload_seq and not row.get("offloading_date") and tracker.get("offloading_date"):
		row.offloading_date = tracker.get("offloading_date")
		changed = True
	elif seq == empty_seq:
		for field in (
			"actual_empty_return",
			"gate_in_date_depot",
		):
			if not row.get(field) and tracker.get(field):
				row.set(field, tracker.get(field))
				changed = True
	elif seq == interchange_seq:
		for field in ("interchange_date", "interchange_document"):
			if not row.get(field) and tracker.get(field):
				row.set(field, tracker.get(field))
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
	book_seq = get_container_task_sequence("custom_book_trucks_task_seq")
	monitor_seq = get_container_task_sequence("custom_monitor_delivery_task_seq")
	vessel_arrival_seq = get_container_task_sequence("custom_vessel_arrival_task_seq")
	for tracker in trackers:
		if tracker.name in existing:
			if _prefill_row_from_tracker(existing[tracker.name], tracker, seq, doc.project):
				changed = True
			continue

		row_data = {
			"container_tracker": tracker.name,
			"container_number": tracker.container_number,
			"cargo_size": tracker_row_cargo_size(tracker),
			"current_status": tracker.status,
		}
		if seq == vessel_arrival_seq:
			row_data["discharging_date"] = (
				tracker.get("discharging_date") or tracker.get("ata") or None
			)
		elif seq in _shipping_line_application_seqs() or seq in _shipping_line_finance_seqs():
			bl_map = _bl_deposit_by_container_number(doc.project)
			src = bl_map.get((tracker.container_number or "").strip().upper()) or {}
			row_data["deposit_amount"] = flt(src.get("deposit_amount"))
		elif seq == book_seq:
			row_data.update(
				{
					"truck_number": tracker.truck_number or "",
					"driver_name": tracker.driver_name or "",
					"driver_contact": tracker.driver_contact or "",
					"transporter": tracker.transporter or "",
				}
			)
		elif seq == monitor_seq:
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
	"""Push filled task container grid rows to linked Container Trackers (partial saves OK).

	Vessel-arrival / Create Entry grid is Project→Task only — never push back from Entry.
	"""
	if not is_container_update_task(doc):
		return
	if not doc.meta.has_field(TASK_CONTAINER_UPDATES_FIELD):
		return

	seq = _sea_task_seq(doc)
	if seq == get_container_task_sequence("custom_vessel_arrival_task_seq"):
		return

	field_pairs = _seq_field_map().get(seq, [])
	if not field_pairs:
		return

	check_fields = set()
	for row in doc.get(TASK_CONTAINER_UPDATES_FIELD) or []:
		tracker_name = row.get("container_tracker")
		if not tracker_name or not frappe.db.exists("Container Tracker", tracker_name):
			continue

		updates: dict[str, Any] = {}
		for task_field, tracker_field in field_pairs:
			val = row.get(task_field)
			if task_field in check_fields:
				updates[tracker_field] = cint(val)
				continue
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


def validate_shipping_line_deposit_declarations(doc) -> None:
	"""Require BL container deposit amounts when arrangement is Container Deposit."""
	if not is_shipping_line_deposit_task(doc):
		return
	if not doc.get("project"):
		return

	from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
		DEPOSIT_ARRANGEMENT_CONTAINER,
		get_bill_of_lading_for_project,
	)

	bl_name = get_bill_of_lading_for_project(doc.project)
	if not bl_name:
		return

	bl = frappe.get_doc("Bill of Lading", bl_name)
	_mirror_bl_deposit_onto_task(doc, bl)

	arrangement = (bl.get("deposit_arrangement") or "").strip()
	if arrangement != DEPOSIT_ARRANGEMENT_CONTAINER:
		return

	amount_missing = []
	for row in bl.get("container_information") or []:
		if flt(row.get("deposit_amount")) <= 0:
			amount_missing.append(row.container_number or row.name)
	if amount_missing and flt(bl.get("deposit_amount")) <= 0:
		frappe.throw(
			_(
				"Bill of Lading <b>{0}</b> has Container Deposit — enter deposit amounts "
				"on each container row: {1}"
			).format(bl.bl_number or bl.name, ", ".join(amount_missing))
		)


def _mirror_bl_deposit_onto_task(doc, bl) -> None:
	"""Copy BL arrangement + per-container amounts onto the task (display only)."""
	from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
		DEPOSIT_ARRANGEMENT_CONTAINER,
	)

	arrangement = (bl.get("deposit_arrangement") or "").strip()
	if doc.meta.has_field("custom_bl_deposit_arrangement"):
		doc.custom_bl_deposit_arrangement = arrangement
	if doc.meta.has_field("custom_bl_has_deposit"):
		doc.custom_bl_has_deposit = 1 if arrangement == DEPOSIT_ARRANGEMENT_CONTAINER else 0
	if doc.meta.has_field("custom_deposit_payer") and bl.get("deposit_payer"):
		doc.custom_deposit_payer = bl.get("deposit_payer")
	if not doc.meta.has_field(TASK_CONTAINER_UPDATES_FIELD):
		return
	by_number = {
		(r.get("container_number") or "").strip().upper(): r
		for r in (bl.get("container_information") or [])
		if (r.get("container_number") or "").strip()
	}
	for row in doc.get(TASK_CONTAINER_UPDATES_FIELD) or []:
		key = (row.get("container_number") or "").strip().upper()
		src = by_number.get(key)
		if not src:
			continue
		row.deposit_amount = flt(src.get("deposit_amount"))


def _bl_deposit_by_container_number(project: str) -> dict[str, dict]:
	from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
		get_bill_of_lading_for_project,
	)

	bl_name = get_bill_of_lading_for_project(project)
	if not bl_name:
		return {}
	return {
		(r.container_number or "").strip().upper(): r
		for r in frappe.get_all(
			"Container",
			filters={"parent": bl_name, "parenttype": "Bill of Lading"},
			fields=["container_number", "deposit_amount", "container_tracker"],
		)
		if (r.container_number or "").strip()
	}


def sync_vessel_arrival_task_rows_from_project(project_name: str) -> None:
	"""Seed/refresh Create Entry container grid after Project port-arrival confirm.

	Does not complete or block Create Entry — Entry paperwork stays independent.
	"""
	if not project_name or frappe.flags.get("cgm_syncing_tracker_to_task"):
		return

	seq = get_container_task_sequence("custom_vessel_arrival_task_seq")
	rows = frappe.get_all(
		"Task",
		filters={
			"project": project_name,
			"custom_task_flow_key": task_flow_key_in_filter(),
			"custom_sequence_no": seq,
			"status": ["!=", "Cancelled"],
		},
		pluck="name",
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return
	task_name = rows[0]

	frappe.flags.cgm_syncing_tracker_to_task = True
	try:
		task = frappe.get_doc("Task", task_name)
		if seed_container_update_rows(task):
			task.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_tracker_to_task = False


def sync_tracker_fields_to_open_task_rows(tracker) -> None:
	"""Push tracker edits back to open transport/delivery task grids."""
	if not tracker.project or frappe.flags.get("cgm_syncing_tracker_to_task"):
		return

	sync_seqs = {
		get_container_task_sequence("custom_vessel_arrival_task_seq"): (
			"discharging_date",
		),
		get_container_task_sequence("custom_book_trucks_task_seq"): TRANSPORT_TRACKER_FIELDS,
		get_container_task_sequence("custom_gate_out_task_seq"): (
			"gate_out_date_port",
			"free_days_start_date",
			"free_days_end_date",
			"kpa_free_days_start_date",
			"kpa_free_days_end_date",
		),
		get_container_task_sequence("custom_monitor_delivery_task_seq"): (
			"gate_in_date_warehouse",
			"delivery_location",
		),
		get_container_task_sequence("custom_offload_task_seq"): ("offloading_date",),
		get_container_task_sequence("custom_empty_return_task_seq"): (
			"actual_empty_return",
			"gate_in_date_depot",
		),
		get_container_task_sequence("custom_interchange_task_seq"): (
			"interchange_date",
			"interchange_document",
		),
	}

	tasks = frappe.get_all(
		"Task",
		filters={
			"project": tracker.project,
			"custom_task_flow_key": task_flow_key_in_filter(),
			"status": ["not in", ["Completed", "Cancelled"]],
			"custom_sequence_no": ["in", list(sync_seqs.keys())],
		},
		fields=["name", "custom_sequence_no"],
	)
	if not tasks:
		return

	frappe.flags.cgm_syncing_tracker_to_task = True
	try:
		for task_row in tasks:
			fields = sync_seqs.get(int(task_row.custom_sequence_no or 0))
			if not fields:
				continue
			task = frappe.get_doc("Task", task_row.name)
			if not task.meta.has_field(TASK_CONTAINER_UPDATES_FIELD):
				continue
			changed = False
			for row in task.get(TASK_CONTAINER_UPDATES_FIELD) or []:
				if row.get("container_tracker") != tracker.name:
					continue
				for field in fields:
					val = tracker.get(field)
					if field == "discharging_date" and not val:
						val = tracker.get("ata")
					if val and row.get(field) != val:
						row.set(field, val)
						changed = True
			if changed:
				task.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_tracker_to_task = False


def _auto_complete_container_task(task_name: str, project: str) -> bool:
	if frappe.flags.get("cgm_auto_completing_container_task"):
		return False

	frappe.flags.cgm_auto_completing_container_task = True
	try:
		frappe.db.set_value(
			"Task",
			task_name,
			{
				"status": "Completed",
				"completed_by": frappe.session.user,
				"completed_on": now_datetime(),
			},
			update_modified=True,
		)
		frappe.clear_document_cache("Task", task_name)
	finally:
		frappe.flags.cgm_auto_completing_container_task = False

	if frappe.flags.get("cgm_skip_task_project_sync"):
		return True

	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		sync_project_shipment_status_from_tasks,
	)

	sync_project_shipment_status_from_tasks(project)
	frappe.publish_realtime(
		"cgm_project_tracking_refresh",
		{"project": project},
		doctype="Project",
		docname=project,
	)
	return True


def try_auto_complete_container_task_for_seq(project: str, seq: int) -> bool:
	"""Complete an open container step task when every tracker has the step field filled."""
	if not project:
		return False

	if not frappe.db.exists(
		"Container Tracker",
		{"project": project},
	):
		return False

	if _containers_missing_step(project, seq):
		return False

	task_name = frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": task_flow_key_in_filter(),
			"custom_sequence_no": seq,
			"status": ["not in", ["Completed", "Cancelled"]],
		},
		"name",
	)
	if not task_name:
		return False

	return _auto_complete_container_task(task_name, project)


def check_all_container_tasks_for_project(project: str) -> None:
	"""After tracker updates, auto-complete any open transport step whose containers are all done."""
	if not project or frappe.flags.get("cgm_checking_container_task_completion"):
		return

	frappe.flags.cgm_checking_container_task_completion = True
	try:
		for seq in _completion_field_by_seq():
			try_auto_complete_container_task_for_seq(project, seq)
	finally:
		frappe.flags.cgm_checking_container_task_completion = False


def after_tracker_interchange_updated(tracker) -> bool:
	"""Push interchange to open task rows and complete Receive interchange when all containers are done."""
	if not tracker or not tracker.project:
		return False
	sync_tracker_fields_to_open_task_rows(tracker)
	return try_auto_complete_container_task_for_seq(
		tracker.project,
		get_container_task_sequence("custom_interchange_task_seq"),
	)


def check_task_container_completion(doc) -> None:
	"""Auto-complete transport tasks when every project container satisfies the step."""
	if frappe.flags.get("cgm_skip_task_project_sync"):
		return
	if doc.status == "Completed":
		return
	if not doc.get("project"):
		return

	seq = _sea_task_seq(doc)
	if not _completion_field_by_seq().get(seq):
		return

	try_auto_complete_container_task_for_seq(doc.project, seq)


def validate_container_step_task_completion(doc) -> None:
	"""Manual Complete only when every container tracker has the step recorded."""
	if not is_sea_import_task(doc):
		return
	if doc.status != "Completed":
		return

	prev = doc.get_doc_before_save()
	if prev and prev.status == "Completed":
		return

	seq = _sea_task_seq(doc)
	if not doc.get("project"):
		return
	if not _completion_field_by_seq().get(seq) and seq != get_container_task_sequence(
		"custom_interchange_task_seq"
	):
		return

	if not frappe.db.exists("Container Tracker", {"project": doc.project}):
		frappe.throw(
			_("Add container trackers on this project before completing transport step tasks.")
		)

	missing = _containers_missing_step(doc.project, seq)
	if missing:
		if seq == get_container_task_sequence("custom_interchange_task_seq"):
			label = _("interchange date and receipt")
		else:
			check_field = _completion_field_by_seq().get(seq) or ""
			label = frappe.unscrub(check_field.replace("_", " "))
		frappe.throw(
			_(
				"Every container must have <b>{0}</b> before completing this task. "
				"Still open: {1}"
			).format(label, ", ".join(missing))
		)


def validate_task_19_container_updates(doc) -> None:
	"""Book-trucks task: truck details for at least one container OR task-level reason."""
	if not is_sea_import_task(doc):
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
	_sync_bl_deposit_fields_on_load(doc)


def _sync_bl_deposit_fields_on_load(doc) -> None:
	"""Mirror BL deposit arrangement onto task fields when the form loads."""
	if not is_shipping_line_deposit_mirror_task(doc) or not doc.get("project"):
		return

	from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
		get_bill_of_lading_for_project,
	)

	bl_name = get_bill_of_lading_for_project(doc.project)
	if not bl_name:
		return
	bl = frappe.get_doc("Bill of Lading", bl_name)
	_mirror_bl_deposit_onto_task(doc, bl)
