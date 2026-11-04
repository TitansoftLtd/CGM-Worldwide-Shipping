"""Task form ↔ Container Tracker sync (tasks are the data-entry UI)."""

from __future__ import annotations

from typing import Any

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.dialogs import (
	blocked_dialog,
)
from frappe import _
from frappe.utils import cint, flt, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CONTAINER_STEP_BOOK_TRUCKS,
	CONTAINER_STEP_BY_SEQ_FIELD,
	CONTAINER_STEP_EMPTY_RETURN,
	CONTAINER_STEP_GATE_OUT,
	CONTAINER_STEP_INTERCHANGE,
	CONTAINER_STEP_MONITOR_DELIVERY,
	CONTAINER_STEP_OFFLOAD,
	CONTAINER_UPDATE_STEPS,
	TASK_CONTAINER_UPDATES_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	container_seq_for_task,
	container_step_for_task,
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


TRANSPORT_TRACKER_FIELDS = (
	"transporter",
	"truck_number",
	"driver_name",
	"driver_contact",
)


# Container Tracker fields each step mirrors onto its task grid, keyed by the
# Settings sequence field. One map: four copies of it had to agree, which is how
# gate_in_date_depot went missing from the seed query.
STEP_SYNC_TRACKER_FIELDS: dict[str, tuple[str, ...]] = {
	"custom_vessel_arrival_task_seq": ("discharging_date",),
	"custom_book_trucks_task_seq": TRANSPORT_TRACKER_FIELDS,
	# Editable at exit too: the truck that turns up is not always the one booked.
	"custom_gate_out_task_seq": TRANSPORT_TRACKER_FIELDS
	+ (
		"gate_out_date_port",
		"free_days_start_date",
		"free_days_end_date",
		"kpa_free_days_start_date",
		"kpa_free_days_end_date",
	),
	"custom_monitor_delivery_task_seq": ("gate_in_date_warehouse", "delivery_location"),
	"custom_offload_task_seq": ("offloading_date",),
	"custom_empty_return_task_seq": ("actual_empty_return", "gate_in_date_depot"),
	"custom_interchange_task_seq": ("interchange_date", "interchange_document"),
}

# A shipping-line task shows the shipment's containers but records no step of its
# own, so nothing used to fill these and they read as blanks that never resolved.
# It is a read-only mirror: it carries the tracker's current truth, not what was
# entered at the time, which is the opposite of how a step grid behaves.
SHIPPING_LINE_MIRROR_FIELDS = (
	"discharging_date",
	"transporter",
	"truck_number",
	"driver_name",
	"driver_contact",
	"gate_out_date_port",
	"actual_empty_return",
	"interchange_date",
)

# Pairs whose task and tracker names differ. Task → tracker only.
STEP_RENAMED_TRACKER_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
	"custom_field_clearance_task_seq": (("verification_location", "current_location"),),
	"custom_offload_task_seq": (("container_emptied_location", "delivery_location"),),
}


def _sync_fields_by_seq() -> dict[int, tuple[str, ...]]:
	"""Container Tracker → task grid, keyed by configured sequence number."""
	return {
		get_container_task_sequence(seq_field): fields
		for seq_field, fields in STEP_SYNC_TRACKER_FIELDS.items()
	}


def _seq_field_map() -> dict[int, list[tuple[str, str]]]:
	"""Task grid field → Container Tracker field, keyed by configured sequence number."""
	mapping: dict[int, list[tuple[str, str]]] = {}
	for seq_field, fields in STEP_SYNC_TRACKER_FIELDS.items():
		mapping.setdefault(get_container_task_sequence(seq_field), []).extend(
			(field, field) for field in fields
		)
	for seq_field, pairs in STEP_RENAMED_TRACKER_FIELDS.items():
		mapping.setdefault(get_container_task_sequence(seq_field), []).extend(pairs)
	# Shipping Line Application: deposit fields are mirrored from Bill of Lading (read-only).
	# Do not map them onto Container Tracker.
	return mapping


def is_shipping_line_deposit_task(doc) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_shipping_line_application,
	)

	return is_sea_import_task(doc) and task_is_shipping_line_application(doc)


def is_shipping_line_deposit_mirror_task(doc) -> bool:
	"""Shipping Line Application or Finance payment tasks that mirror BL deposit fields."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_shipping_line_application,
		task_is_shipping_line_finance,
	)

	return is_sea_import_task(doc) and (
		task_is_shipping_line_application(doc) or task_is_shipping_line_finance(doc)
	)


# A step used to close on one Container Tracker field, and the rest of the row could
# stay blank: Book Trucks signed itself off on a truck number alone, with no
# transporter and no driver recorded against the container. That is precisely the
# record wanted months later, when a shipping line bills for demurrage and the
# question is who held the box and when the depot took it back.
#
# These are the fields every container must carry before a step completes itself.
# Settings overrides them per step; an empty table means this set, never "nothing
# required" (see container_step_requirements).
DEFAULT_CONTAINER_STEP_REQUIREMENTS: dict[str, tuple[str, ...]] = {
	CONTAINER_STEP_BOOK_TRUCKS: TRANSPORT_TRACKER_FIELDS,
	CONTAINER_STEP_GATE_OUT: ("gate_out_date_port",),
	CONTAINER_STEP_MONITOR_DELIVERY: ("gate_in_date_warehouse",),
	CONTAINER_STEP_OFFLOAD: ("offloading_date",),
	CONTAINER_STEP_EMPTY_RETURN: ("actual_empty_return", "gate_in_date_depot"),
	CONTAINER_STEP_INTERCHANGE: ("interchange_date", "interchange_document"),
}

CONTAINER_STEP_REQUIREMENT_FIELD = "custom_container_step_requirements"


def container_step_requirements() -> dict[str, tuple[str, ...]]:
	"""Tracker fields each container step needs, from Settings or the defaults.

	Kept configurable because the list is a business judgement, not a rule of the
	trade: it was agreed once, and the next month of real shipments will move it.
	A deploy per adjustment would have put that out of reach of the people who know.
	"""
	configured: dict[str, list[str]] = {}
	try:
		settings = frappe.get_cached_doc("CGM Shipping Settings")
		if settings.meta.has_field(CONTAINER_STEP_REQUIREMENT_FIELD):
			for row in settings.get(CONTAINER_STEP_REQUIREMENT_FIELD) or []:
				step = (row.get("container_step") or "").strip()
				field = (row.get("tracker_field") or "").strip()
				if not step or not field:
					continue
				if field not in configured.setdefault(step, []):
					configured[step].append(field)
	except Exception:
		# Settings unreadable (install, patch, broken row): the defaults still gate.
		configured = {}

	meta = frappe.get_meta("Container Tracker")
	out: dict[str, tuple[str, ...]] = {}
	for step, defaults in DEFAULT_CONTAINER_STEP_REQUIREMENTS.items():
		wanted = configured.get(step) or list(defaults)
		# A field named in Settings but absent from the tracker would hold the step
		# open for good, with nowhere for anyone to go and fill it.
		usable = tuple(f for f in wanted if meta.has_field(f))
		out[step] = usable or tuple(f for f in defaults if meta.has_field(f))
	return out


def ensure_container_step_requirements() -> None:
	"""Seed the default rows so the table shows what is actually enforced.

	Seeded rather than left empty: an empty table tells the reader nothing about
	which details a step waits for, and the point of moving the list into Settings
	was for the people who know the trade to read it and change it. Only ever when
	empty, because rows someone has edited are theirs, not ours to restore.
	"""
	if not frappe.db.exists("DocType", "CGM Container Step Requirement"):
		return
	settings = frappe.get_single("CGM Shipping Settings")
	if not settings.meta.has_field(CONTAINER_STEP_REQUIREMENT_FIELD):
		return
	if settings.get(CONTAINER_STEP_REQUIREMENT_FIELD):
		return

	meta = frappe.get_meta("Container Tracker")
	for step, fields in DEFAULT_CONTAINER_STEP_REQUIREMENTS.items():
		for field in fields:
			if not meta.has_field(field):
				continue
			settings.append(
				CONTAINER_STEP_REQUIREMENT_FIELD,
				{
					"container_step": step,
					"tracker_field": field,
					"field_label": container_tracker_field_label(field),
				},
			)
	settings.flags.ignore_permissions = True
	settings.flags.ignore_mandatory = True
	settings.save()


def validate_container_step_requirement_rows(settings) -> None:
	"""Name each row's field as the tracker names it, and drop repeats."""
	if not settings.meta.has_field(CONTAINER_STEP_REQUIREMENT_FIELD):
		return
	rows = settings.get(CONTAINER_STEP_REQUIREMENT_FIELD) or []
	meta = frappe.get_meta("Container Tracker")
	seen: set[tuple[str, str]] = set()
	keep = []
	for row in rows:
		step = (row.container_step or "").strip()
		field = (row.tracker_field or "").strip()
		if not step or not field or (step, field) in seen:
			continue
		if not meta.has_field(field):
			frappe.throw(
				_(
					"{0} is not a field on the Container Tracker, so a step waiting for it "
					"could never be closed. Remove the row or pick another field."
				).format(frappe.bold(field))
			)
		row.field_label = container_tracker_field_label(field)
		seen.add((step, field))
		keep.append(row)
	if len(keep) != len(rows):
		settings.set(CONTAINER_STEP_REQUIREMENT_FIELD, keep)


def _gated_step_by_seq() -> dict[int, str]:
	"""Configured sequence number → container step, for the steps that gate."""
	return {
		get_container_task_sequence(seq_field): step
		for seq_field, step in CONTAINER_STEP_BY_SEQ_FIELD.items()
		if step in DEFAULT_CONTAINER_STEP_REQUIREMENTS
	}


def _required_fields_by_seq() -> dict[int, tuple[str, ...]]:
	requirements = container_step_requirements()
	return {
		seq: requirements[step]
		for seq, step in _gated_step_by_seq().items()
		if requirements.get(step)
	}


def container_tracker_field_label(field: str) -> str:
	"""The field's name in the tracker form's own words.

	Read from the tracker rather than from a list kept here: gate_out_date_port
	reads "Gate Out Mombasa" on the form, and a dialog that invents its own name for
	a field sends people looking for something that is not there.
	"""
	try:
		df = frappe.get_meta("Container Tracker").get_field(field)
	except Exception:
		df = None
	return (df.label if df and df.label else "") or frappe.unscrub(field)


def container_step_requirement_label(seq: int) -> str:
	"""What the Container Tracker still needs for this step, as the form names it."""
	fields = _required_fields_by_seq().get(seq) or ()
	labels = [container_tracker_field_label(f) for f in fields]
	if not labels:
		return ""
	if len(labels) == 1:
		return labels[0]
	return "{0} and {1}".format(", ".join(labels[:-1]), labels[-1])


def transport_step_tracker_blockers(task) -> tuple[str, list[str]]:
	"""(what the tracker needs, containers short of it) for a transport step task.

	Transport steps are not completed by hand: the tracker drives them, and the task
	marks itself Completed once every container has the step's fields. Callers use
	this to name the containers actually holding a task up, so the gate functions are
	reused rather than restated and the message cannot drift from the rule.
	"""
	seq = int(task.get("custom_sequence_no") or 0)
	if not seq or not task.get("project"):
		return "", []
	if not _required_fields_by_seq().get(seq):
		return "", []
	return container_step_requirement_label(seq), _step_shortfall_lines(task.project, seq)


def _missing_step_fields(tracker: dict, fields: tuple[str, ...]) -> list[str]:
	"""Labels of the step's fields this container has not got."""
	missing = []
	for field in fields:
		value = tracker.get(field)
		if isinstance(value, str):
			value = value.strip()
		if not value:
			missing.append(container_tracker_field_label(field))
	return missing


def _step_shortfall(project: str, seq: int) -> dict[str, list[str]]:
	"""Container → the step's fields it is still missing, for each one short of any."""
	fields = _required_fields_by_seq().get(seq) or ()
	if not fields or not project:
		return {}

	columns = ["name", "container_number"]
	columns += [f for f in fields if f not in columns]
	trackers = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=columns,
		order_by="container_number asc",
	)

	shortfall: dict[str, list[str]] = {}
	for tracker in trackers:
		missing = _missing_step_fields(tracker, fields)
		if missing:
			shortfall[tracker.container_number or tracker.name] = missing
	return shortfall


def _step_shortfall_lines(project: str, seq: int) -> list[str]:
	"""Containers holding a step open, each naming what it is short of.

	A step needing one field reads as the container alone, as it always has. One
	needing several says which of them this container is missing, because "fill in
	the details" sent people back to a row where most cells were already full.
	"""
	shortfall = _step_shortfall(project, seq)
	multi = len(_required_fields_by_seq().get(seq) or ()) > 1
	if not multi:
		return list(shortfall)
	return [
		"{0} ({1})".format(container, ", ".join(missing))
		for container, missing in shortfall.items()
	]


def _containers_missing_step(project: str, seq: int) -> list[str]:
	return list(_step_shortfall(project, seq))


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
	"gate_in_date_depot",
	"delivery_location",
]


def _container_seq(doc) -> int:
	"""Settings key number of the task's Container Step (see container_step_for_task).

	Container code keys on this, never on the task's own position in the plan.
	"""
	return container_seq_for_task(doc)


def _container_step_task_rows(
	project: str, seqs, *, exclude_statuses=("Completed", "Cancelled")
) -> list:
	"""The project's tasks recording one of the container steps keyed by *seqs*.

	Matched on each task's Container Step stamp, so its own step number never
	decides it. Rows carry ``container_seq``; newest first.
	"""
	if not project or not seqs:
		return []
	fields = ["name", "creation", "custom_sequence_no", "custom_task_flow_key", "custom_task_role"]
	if frappe.get_meta("Task").has_field("custom_container_step"):
		fields.append("custom_container_step")
	rows = frappe.get_all(
		"Task",
		filters={
			"project": project,
			"custom_task_flow_key": task_flow_key_in_filter(),
			"status": ["not in", list(exclude_statuses)],
		},
		fields=fields,
		order_by="creation desc",
	)
	out = []
	for row in rows:
		row.container_seq = container_seq_for_task(row)
		if row.container_seq in seqs:
			out.append(row)
	return out


def is_container_update_task(doc) -> bool:
	"""Container step tasks and the Shipping Line deposit steps show the grid."""
	if not is_sea_import_task(doc):
		return False
	return container_step_for_task(doc) in CONTAINER_UPDATE_STEPS or is_shipping_line_deposit_mirror_task(doc)


def _mirror_tracker_fields_onto_row(row, tracker: dict) -> bool:
	"""Put the tracker's current container detail on a read-only mirror row."""
	changed = False
	for field in SHIPPING_LINE_MIRROR_FIELDS:
		value = tracker.get(field)
		if field == "discharging_date" and not value:
			value = tracker.get("ata")
		if value and row.get(field) != value:
			row.set(field, value)
			changed = True
	return changed


def _shipping_line_mirror_tasks(project: str) -> list:
	"""The project's shipping-line tasks. They mirror containers but own no step."""
	if not project:
		return []
	rows = frappe.get_all(
		"Task",
		filters={
			"project": project,
			"custom_task_flow_key": task_flow_key_in_filter(),
			"status": ["not in", ("Cancelled",)],
		},
		fields=[
			"name",
			"custom_task_role",
			"custom_payment_kind",
			"custom_task_flow_key",
			"custom_sequence_no",
		],
	)
	return [row for row in rows if is_shipping_line_deposit_mirror_task(row)]


def _prefill_row_from_tracker(
	row, tracker: dict, seq: int, project: str | None = None, *, shipping_line: bool = False
) -> bool:
	changed = False
	if row.current_status != tracker.get("status"):
		row.current_status = tracker.get("status")
		changed = True

	vessel_arrival_seq = get_container_task_sequence("custom_vessel_arrival_task_seq")

	if seq == vessel_arrival_seq:
		# Project confirm is the source of truth — keep grid in sync with trackers.
		discharge = tracker.get("discharging_date") or tracker.get("ata")
		if discharge and row.get("discharging_date") != discharge:
			row.discharging_date = discharge
			changed = True
	elif shipping_line:
		bl_map = _bl_deposit_by_container_number(project or tracker.get("project") or "")
		src = bl_map.get((tracker.get("container_number") or "").strip().upper()) or {}
		new_amt = flt(src.get("deposit_amount"))
		if flt(row.get("deposit_amount")) != new_amt:
			row.deposit_amount = new_amt
			changed = True
		if _mirror_tracker_fields_onto_row(row, tracker):
			changed = True
	else:
		# Blanks only: a filled cell records what was entered against the step.
		for field in _sync_fields_by_seq().get(seq) or ():
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

	seq = _container_seq(doc)
	shipping_line = is_shipping_line_deposit_mirror_task(doc)
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
		row = existing.get(tracker.name)
		if row is None:
			# New rows take the same prefill as existing ones, or a step whose columns
			# the prefill knows about would still be born blank.
			row = doc.append(
				TASK_CONTAINER_UPDATES_FIELD,
				{
					"container_tracker": tracker.name,
					"container_number": tracker.container_number,
					"cargo_size": tracker_row_cargo_size(tracker),
					"current_status": tracker.status,
				},
			)
			changed = True
		if _prefill_row_from_tracker(
			row, tracker, seq, doc.project, shipping_line=shipping_line
		):
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

	seq = _container_seq(doc)
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
		blocked_dialog(
			_("Container deposit amounts missing"),
			_("This Bill of Lading carries a container deposit, so each row needs its amount:"),
			[
				(
					_("Deposit amount missing on: {0}").format(", ".join(amount_missing)),
					_("Enter it on each container row of <b>{0}</b>.").format(
						bl.bl_number or bl.name
					),
				)
			],
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
	rows = _container_step_task_rows(project_name, {seq}, exclude_statuses=("Cancelled",))
	if not rows:
		return
	task_name = rows[0].name

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

	sync_seqs = _sync_fields_by_seq()

	targets = [
		(row.name, sync_seqs.get(row.container_seq))
		for row in _container_step_task_rows(tracker.project, set(sync_seqs))
	]
	# Shipping-line tasks own no step, so they never matched the loop above and
	# their container grid sat blank however often the tracker changed.
	targets += [
		(row.name, SHIPPING_LINE_MIRROR_FIELDS)
		for row in _shipping_line_mirror_tasks(tracker.project)
	]
	tasks = [(name, fields) for name, fields in targets if fields]
	if not tasks:
		return

	frappe.flags.cgm_syncing_tracker_to_task = True
	try:
		for task_name, fields in tasks:
			task = frappe.get_doc("Task", task_name)
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


def backfill_finished_task_rows_from_tracker(tracker) -> int:
	"""Fill blank cells on finished tasks' container rows from the tracker.

	The live sync skips Completed and Cancelled tasks, and for a cell that already
	holds a value that is right: a finished task is a record of what was done at the
	time, and rewriting it would destroy the trail rather than complete it.

	A blank cell records nothing, though. Transport details entered on the Container
	Tracker after the step was signed off never reached the task grid at all, so the
	grid stayed empty and whoever opened the task months later, chasing a late
	container, found nothing there. That is the hole this fills, and only that: a cell
	with a value is never touched.

	Returns how many tasks were changed.
	"""
	if not tracker.project or frappe.flags.get("cgm_syncing_tracker_to_task"):
		return 0

	seq_fields = _finished_backfill_fields()
	tasks = _container_step_task_rows(
		tracker.project, set(seq_fields), exclude_statuses=("Cancelled",)
	)
	if not tasks:
		return 0

	changed_tasks = 0
	frappe.flags.cgm_syncing_tracker_to_task = True
	try:
		for task_row in tasks:
			fields = seq_fields.get(task_row.container_seq)
			if not fields:
				continue

			task = frappe.get_doc("Task", task_row.name)
			# The open ones are already handled by the live sync; doing them here too
			# would mean two writes for the same edit.
			if task.status != "Completed":
				continue
			if not task.meta.has_field(TASK_CONTAINER_UPDATES_FIELD):
				continue

			changed = False
			for row in task.get(TASK_CONTAINER_UPDATES_FIELD) or []:
				if row.get("container_tracker") != tracker.name:
					continue
				for field in fields:
					if row.get(field):
						continue  # already recorded; not ours to overwrite
					value = tracker.get(field)
					if field == "discharging_date" and not value:
						value = tracker.get("ata")
					if value:
						row.set(field, value)
						changed = True

			if changed:
				task.save(ignore_permissions=True)
				changed_tasks += 1
	finally:
		frappe.flags.cgm_syncing_tracker_to_task = False

	return changed_tasks


def _finished_backfill_fields() -> dict[int, tuple[str, ...]]:
	"""The same step-to-field map the live sync uses, from the one source."""
	return _sync_fields_by_seq()


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
	_refresh_erpnext_project_rollup(project)
	frappe.publish_realtime(
		"cgm_project_tracking_refresh",
		{"project": project},
		doctype="Project",
		docname=project,
	)
	return True


def _refresh_erpnext_project_rollup(project: str) -> None:
	"""Recompute ERPNext's own % Complete after a status written with db.set_value.

	set_value skips document hooks, which is what keeps this fast, but it also means
	Task.update_project() never fires and the Project keeps the percentage it had
	before. A shipment whose last transport steps auto-completed then sat at 91%
	with every task done, because those two steps are exactly the ones completed
	this way (PROJ-0003, PROJ-0039). CGM's own custom_shipment_status was right the
	whole time - only ERPNext's rollup was stale, which is why the two disagreed.
	"""
	if not project or not frappe.db.exists("Project", project):
		return
	try:
		frappe.get_cached_doc("Project", project).update_project()
	except Exception:
		# A stale percentage is cosmetic; never fail a task completion over it.
		frappe.log_error(
			title="cgm container task project rollup",
			message=f"{project}: {frappe.get_traceback()}",
		)


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

	rows = _container_step_task_rows(project, {seq})
	if not rows:
		return False

	return _auto_complete_container_task(rows[0].name, project)


def check_all_container_tasks_for_project(project: str) -> None:
	"""After tracker updates, auto-complete any open transport step whose containers are all done."""
	if not project or frappe.flags.get("cgm_checking_container_task_completion"):
		return

	frappe.flags.cgm_checking_container_task_completion = True
	try:
		for seq in _required_fields_by_seq():
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

	seq = _container_seq(doc)
	if not _required_fields_by_seq().get(seq):
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

	seq = _container_seq(doc)
	if not doc.get("project"):
		return
	if not _required_fields_by_seq().get(seq):
		return

	if not frappe.db.exists("Container Tracker", {"project": doc.project}):
		blocked_dialog(
			_("No containers on this shipment"),
			_("Transport steps are tracked per container, and this project has none:"),
			[
				(
					_("Container Tracker is empty"),
					_("Add the containers on this project, then this step can complete."),
				)
			],
		)

	missing = _step_shortfall_lines(doc.project, seq)
	if missing:
		label = container_step_requirement_label(seq)
		blocked_dialog(
			_("Waiting on the Container Tracker"),
			_("This step completes on its own once every container has its details:"),
			[
				(
					_("{0} missing on: {1}").format(label, ", ".join(missing)),
					_(
						"Fill it on the <b>Container Tracker</b> for this shipment and the "
						"task completes itself."
					),
				)
			],
		)


def validate_book_trucks_container_updates(doc) -> None:
	"""Book-trucks task: truck details for at least one container OR task-level reason."""
	if not is_sea_import_task(doc):
		return
	if _container_seq(doc) != get_container_task_sequence("custom_book_trucks_task_seq"):
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
		blocked_dialog(
			_("Trucks not booked yet"),
			_("Either of these closes this step:"),
			[
				(
					_("Truck details"),
					_("Enter the truck number on at least one container row."),
				),
				(
					_("Reason instead"),
					_(
						"If the containers are not exiting port, say why in "
						"<b>Not Emptied Reason</b>."
					),
				),
			],
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
