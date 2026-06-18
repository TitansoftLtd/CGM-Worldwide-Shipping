"""Container Tracker — per-container lifecycle engine (one tracker = one physical container)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	BULK_CONTAINER_TASK_SEQ_FIELDS,
	CONTAINER_SPECIFIC_TASK_SEQ_FIELDS,
	CONTAINER_STATUS_AT_WAREHOUSE,
	CONTAINER_STATUS_CARGO_OFFLOADED,
	CONTAINER_STATUS_DISCHARGED_AT_PORT,
	CONTAINER_STATUS_EMPTY_RETURNED,
	CONTAINER_STATUS_INTERCHANGE,
	CONTAINER_STATUS_PENDING_ARRIVAL,
	CONTAINER_STATUS_RELEASED_IN_TRANSIT,
	CONTAINER_STATUS_RETURN_OVERDUE,
	CONTAINER_STATUS_VESSEL_BERTHED,
	CONTAINER_TASK_SEQ_DEFAULTS,
	DEPOSIT_REFUND_STATUSES,
	TASK_CONTAINER_NUMBER_FIELD,
	TASK_CONTAINER_TRACKER_FIELD,
	TASK_TYPE_OF_CONTAINER_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipping_line_rates import (
	COUNT_FROM_BERTHING,
	COUNT_FROM_DISCHARGE,
	build_rate_source_label,
	default_destination_name,
	get_free_days_rule,
	get_valid_destinations,
	resolve_container_category,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	get_container_table_field_for_doctype,
)


class ContainerEventResolutionError(frappe.ValidationError):
	pass


def get_container_task_sequence(fieldname: str) -> int:
	default = CONTAINER_TASK_SEQ_DEFAULTS.get(fieldname)
	if default is None:
		frappe.throw(f"Unknown container task sequence field: {fieldname}")
	if frappe.db.exists("DocType", "CGM Shipping Settings"):
		meta = frappe.get_meta("CGM Shipping Settings")
		if meta.has_field(fieldname):
			val = frappe.db.get_single_value("CGM Shipping Settings", fieldname)
			if val:
				return int(val)
	return default


def get_gate_out_task_sequence() -> int:
	return get_container_task_sequence("custom_gate_out_task_seq")


def get_empty_return_task_sequence() -> int:
	return get_container_task_sequence("custom_empty_return_task_seq")


@frappe.request_cache
def _bulk_task_sequences() -> frozenset[int]:
	return frozenset(get_container_task_sequence(f) for f in BULK_CONTAINER_TASK_SEQ_FIELDS)


@frappe.request_cache
def _container_specific_task_sequences() -> frozenset[int]:
	return frozenset(
		get_container_task_sequence(f) for f in CONTAINER_SPECIFIC_TASK_SEQ_FIELDS
	)


def is_bulk_container_event(seq: int) -> bool:
	return seq in _bulk_task_sequences()


def is_container_specific_event(seq: int) -> bool:
	return seq in _container_specific_task_sequences()


def get_default_kpa_free_days() -> int:
	if frappe.db.exists("DocType", "CGM Shipping Settings"):
		meta = frappe.get_meta("CGM Shipping Settings")
		if meta.has_field("custom_kpa_free_days"):
			val = frappe.db.get_single_value("CGM Shipping Settings", "custom_kpa_free_days")
			if val is not None:
				return int(val)
	return 5


def _days_between(start, end) -> int | None:
	start_date = getdate(start)
	end_date = getdate(end)
	if not start_date or not end_date:
		return None
	return max(0, (end_date - start_date).days)


def _optional_date(value):
	"""Return a date only when a value exists; avoid getdate(None)=>today side effects."""
	if not value:
		return None
	return getdate(value)


def _derived_free_days(data: dict[str, Any]) -> int:
	from_dates = _days_between(
		data.get("free_days_start_date"), data.get("free_days_end_date")
	)
	if from_dates is not None:
		return from_dates
	return int(data.get("free_days") or 0)


def _derived_detention_free_days(data: dict[str, Any]) -> int:
	from_dates = _days_between(
		data.get("detention_free_start_date"), data.get("detention_free_end_date")
	)
	if from_dates is not None:
		return from_dates
	return int(data.get("detention_free_days") or 0)


def _anchor_date(doc: dict[str, Any] | object) -> Any:
	data = doc if isinstance(doc, dict) else doc.as_dict()
	return (
		data.get("free_days_start_date")
		or data.get("discharging_date")
		or data.get("ata")
		or data.get("icd_mombasa_discharge_date")
	)


def populate_rates_from_shipping_line(doc, *, force: bool = False) -> None:
	"""Apply Supplier rule defaults at tracker creation only — not used at calculation time."""
	if not doc.get("shipping_line") or doc.get("__islocal"):
		return

	destination = doc.get("delivery_destination") or _project_delivery_destination(
		doc.get("project")
	)
	category = resolve_container_category(
		doc.get("type_of_container"), doc.get("container_number")
	)
	rule = get_free_days_rule(doc.shipping_line, destination, category)

	if force:
		if rule:
			doc.free_days = int(rule.get("free_days") or 0)
			doc.detention_free_days = int(
				rule.get("detention_free_days") or rule.get("free_days") or 0
			)
			doc.free_days_count_from = rule.get("count_from") or COUNT_FROM_DISCHARGE
			doc.rate_source = build_rate_source_label(
				doc.shipping_line, destination, category, rule
			)
		else:
			doc.free_days = 0
			if doc.get("detention_free_days") is None:
				doc.detention_free_days = 0
		doc.kpa_free_days = get_default_kpa_free_days()
	elif rule:
		if doc.get("free_days") is None:
			doc.free_days = int(rule.get("free_days") or 0)
		if doc.get("detention_free_days") is None:
			doc.detention_free_days = int(
				rule.get("detention_free_days") or rule.get("free_days") or 0
			)
		doc.free_days_count_from = rule.get("count_from") or COUNT_FROM_DISCHARGE
		doc.rate_source = build_rate_source_label(
			doc.shipping_line, destination, category, rule
		)


def _project_delivery_destination(project_name: str | None) -> str:
	if not project_name:
		return default_destination_name()
	if frappe.get_meta("Project").has_field("custom_delivery_destination"):
		val = frappe.db.get_value("Project", project_name, "custom_delivery_destination")
		if val:
			return _normalize_destination(val)
	return default_destination_name()


def _normalize_destination(value: str) -> str:
	label = (value or "").strip()
	if label:
		for dest in get_valid_destinations():
			if dest.lower() == label.lower():
				return dest
	return default_destination_name()


def compute_container_metrics(data: dict[str, Any]) -> dict[str, Any]:
	ref_date = getdate(today())
	anchor = _optional_date(_anchor_date(data))
	gate_out = _optional_date(data.get("gate_out_date_port"))
	actual_return = _optional_date(data.get("actual_empty_return"))
	offloading = _optional_date(data.get("offloading_date"))
	delivery = _optional_date(data.get("delivery_date"))
	gate_in_wh = _optional_date(data.get("gate_in_date_warehouse"))
	interchange = _optional_date(data.get("interchange_date"))
	discharging = _optional_date(data.get("discharging_date"))
	ata = _optional_date(data.get("ata"))

	free_days = _derived_free_days(data)
	detention_free = _derived_detention_free_days(data)
	demurrage_rate = flt(data.get("demurrage_daily_rate"))
	detention_rate = flt(data.get("detention_daily_rate"))
	kpa_free = int(data.get("kpa_free_days") or get_default_kpa_free_days())
	kpa_rate = flt(data.get("kpa_daily_rate"))

	out: dict[str, Any] = {
		"free_days": free_days,
		"detention_free_days": detention_free,
		"port_days_used": 0,
		"demurrage_start_date": None,
		"demurrage_days": 0,
		"demurrage_amount": 0.0,
		"kpa_days": 0,
		"kpa_amount": 0.0,
		"detention_days": 0,
		"detention_amount": 0.0,
		"expected_empty_return": None,
		"days_outstanding": 0,
		"status": CONTAINER_STATUS_PENDING_ARRIVAL,
		"alert_status": "",
	}

	if anchor and free_days:
		out["demurrage_start_date"] = anchor + timedelta(days=free_days)

	if anchor:
		end_port = gate_out or ref_date
		port_days = max(0, (end_port - anchor).days)
		out["port_days_used"] = port_days
		dem_days = max(0, port_days - free_days) if free_days else 0
		out["demurrage_days"] = dem_days
		out["demurrage_amount"] = flt(dem_days * demurrage_rate)
		kpa_days = max(0, port_days - kpa_free)
		out["kpa_days"] = kpa_days
		out["kpa_amount"] = flt(kpa_days * kpa_rate)

	if gate_out and detention_free:
		out["expected_empty_return"] = gate_out + timedelta(days=detention_free)

	if gate_out:
		end_det = actual_return or ref_date
		days_out = max(0, (end_det - gate_out).days)
		det_days = max(0, days_out - detention_free) if detention_free else 0
		out["detention_days"] = det_days
		out["detention_amount"] = flt(det_days * detention_rate)

	expected = _optional_date(out.get("expected_empty_return"))
	if expected and not actual_return and ref_date > expected:
		out["days_outstanding"] = (ref_date - expected).days

	out["status"] = _derive_status(
		interchange=interchange,
		actual_return=actual_return,
		expected_return=expected,
		offloading=offloading,
		gate_in_wh=gate_in_wh,
		gate_out=gate_out,
		discharging=discharging,
		ata=ata,
		ref_date=ref_date,
	)
	out["alert_status"] = _derive_alert_status(
		discharging=discharging,
		gate_out=gate_out,
		free_days=free_days,
		actual_return=actual_return,
		expected_return=expected,
		ref_date=ref_date,
	)
	return out


_COMPUTED_ONLY_METRIC_FIELDS = frozenset({"alert_status"})


def apply_metrics_to_doc(doc) -> None:
	metrics = compute_container_metrics(doc.as_dict())
	for field, value in metrics.items():
		if field in _COMPUTED_ONLY_METRIC_FIELDS:
			continue
		setattr(doc, field, value)


def _derive_status(
	*,
	interchange,
	actual_return,
	expected_return,
	offloading,
	gate_in_wh,
	gate_out,
	discharging,
	ata,
	ref_date,
) -> str:
	if interchange:
		return CONTAINER_STATUS_INTERCHANGE
	if actual_return:
		return CONTAINER_STATUS_EMPTY_RETURNED
	if expected_return and ref_date > expected_return and not actual_return:
		return CONTAINER_STATUS_RETURN_OVERDUE
	if offloading:
		return CONTAINER_STATUS_CARGO_OFFLOADED
	if gate_in_wh:
		return CONTAINER_STATUS_AT_WAREHOUSE
	if gate_out:
		return CONTAINER_STATUS_RELEASED_IN_TRANSIT
	if discharging:
		return CONTAINER_STATUS_DISCHARGED_AT_PORT
	if ata:
		return CONTAINER_STATUS_VESSEL_BERTHED
	return CONTAINER_STATUS_PENDING_ARRIVAL


def _derive_alert_status(
	*,
	discharging,
	gate_out,
	free_days,
	actual_return,
	expected_return,
	ref_date,
) -> str:
	"""Urgency overlay on operational status. Not stored in DB."""
	if not discharging:
		return ""

	if not gate_out:
		if free_days:
			days_in_port = max(0, (ref_date - discharging).days)
			days_remaining = free_days - days_in_port
			if days_remaining <= 0:
				return "🔴 Demurrage Accruing"
			if days_remaining <= 3:
				return "⚠️ Free Days Expiring Soon"
		return ""

	if not actual_return and expected_return:
		if ref_date > expected_return:
			overdue_days = (ref_date - expected_return).days
			return f"🚨 Return Overdue ({overdue_days} days)"
		days_to_return = (expected_return - ref_date).days
		if days_to_return <= 3:
			return f"⚠️ Return Due in {days_to_return} days"

	if actual_return and expected_return and actual_return <= expected_return:
		return "✅ Returned On Time"

	return ""


def _derive_container_mode(project) -> str:
	delivery_type = (project.get("custom_delivery_type") or "").lower()
	if "icd" in delivery_type:
		return "ICD Nairobi"
	if "transit" in delivery_type or "border" in delivery_type:
		return "Transit Kenya→Border"

	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
		container_tracking_mode_for_shipment_type,
	)

	tracked = container_tracking_mode_for_shipment_type(
		project.get("custom_shipment_type"),
		project.get("custom_mode_of_transport"),
	)
	if tracked:
		return tracked
	return "Mombasa Port"


def find_tracker_by_identity(
	project_name: str,
	container_number: str,
	type_of_container: str | None = None,
) -> str | None:
	if not project_name or not container_number:
		return None
	filters: dict[str, Any] = {
		"project": project_name,
		"container_number": container_number,
	}
	if type_of_container:
		filters["type_of_container"] = type_of_container
	return frappe.db.get_value("Container Tracker", filters, "name")


def _container_identity_filters(
	project_name: str,
	container_number: str,
	type_of_container: str | None,
) -> dict[str, Any]:
	filters: dict[str, Any] = {
		"project": project_name,
		"container_number": container_number,
	}
	if type_of_container:
		filters["type_of_container"] = type_of_container
	return filters


def resolve_single_tracker(
	project_name: str,
	*,
	container_tracker: str | None = None,
	container_number: str | None = None,
	type_of_container: str | None = None,
) -> frappe.Document:
	"""Resolve exactly one Container Tracker for a container-specific lifecycle event."""
	if container_tracker:
		if not frappe.db.exists("Container Tracker", container_tracker):
			frappe.throw(
				_("Container Tracker {0} does not exist.").format(container_tracker),
				ContainerEventResolutionError,
			)
		ct = frappe.get_doc("Container Tracker", container_tracker)
		if ct.project != project_name:
			frappe.throw(
				_(
					"Container Tracker {0} belongs to project {1}, not {2}."
				).format(container_tracker, ct.project, project_name),
				ContainerEventResolutionError,
			)
		return ct

	if not container_number:
		frappe.throw(
			_(
				"This task affects a single container. Set <b>Container Tracker</b> "
				"or <b>Container Number</b> (+ Type of Container when required) on the Task."
			),
			ContainerEventResolutionError,
		)

	filters = _container_identity_filters(
		project_name, container_number, type_of_container
	)
	names = frappe.get_all(
		"Container Tracker",
		filters=filters,
		pluck="name",
		limit=2,
	)

	if len(names) == 1:
		return frappe.get_doc("Container Tracker", names[0])

	if len(names) > 1:
		frappe.throw(
			_(
				"Multiple Container Tracker records match container <b>{0}</b> on this project. "
				"Set <b>Type of Container</b> or link the exact <b>Container Tracker</b>."
			).format(container_number),
			ContainerEventResolutionError,
		)

	if not type_of_container:
		without_type = frappe.get_all(
			"Container Tracker",
			filters={"project": project_name, "container_number": container_number},
			pluck="name",
			limit=2,
		)
		if len(without_type) > 1:
			frappe.throw(
				_(
					"Container <b>{0}</b> appears more than once on this project. "
					"Set <b>Type of Container</b> or link the exact <b>Container Tracker</b>."
				).format(container_number),
				ContainerEventResolutionError,
			)

	frappe.throw(
		_(
			"No Container Tracker found for container <b>{0}</b> on project <b>{1}</b>. "
			"Complete Task 11 (Create Entry) first or check the container identity."
		).format(container_number, project_name),
		ContainerEventResolutionError,
	)


def _event_context_from_task(task_doc) -> dict[str, Any]:
	if not task_doc:
		return {}
	return {
		"container_tracker": task_doc.get(TASK_CONTAINER_TRACKER_FIELD),
		"container_number": task_doc.get(TASK_CONTAINER_NUMBER_FIELD),
		"type_of_container": task_doc.get(TASK_TYPE_OF_CONTAINER_FIELD),
	}


def _resolve_tracker_from_row_link(project_name: str, row) -> frappe.Document | None:
	tracker_name = row.get("container_tracker")
	if not tracker_name or not frappe.db.exists("Container Tracker", tracker_name):
		return None
	ct = frappe.get_doc("Container Tracker", tracker_name)
	if ct.project != project_name:
		return None
	if (
		ct.container_number == row.container_number
		and (ct.type_of_container or "") == (row.get("type_of_container") or "")
	):
		return ct
	return None


def _link_container_row(row, tracker_name: str) -> None:
	if row.get("container_tracker") != tracker_name:
		row.db_set("container_tracker", tracker_name, update_modified=False)


def _link_bl_container_trackers(project) -> None:
	bl_name = project.get("custom_bill_of_lading")
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return

	for row in frappe.get_all(
		"Container",
		filters={"parent": bl_name, "parenttype": "Bill of Lading"},
		fields=["name", "container_number", "type_of_container"],
	):
		if not row.container_number:
			continue
		tracker_name = find_tracker_by_identity(
			project.name, row.container_number, row.type_of_container
		)
		if tracker_name and row.get("container_tracker") != tracker_name:
			frappe.db.set_value(
				"Container",
				row.name,
				"container_tracker",
				tracker_name,
				update_modified=False,
			)


def _populate_tracker_from_project_and_row(ct, project, row, *, at_creation: bool = False) -> None:
	ct.project = project.name
	ct.container_number = row.container_number
	ct.type_of_container = row.get("type_of_container")
	ct.seal_no = row.get("seal_no")
	ct.bl_number = project.get("custom_bill_of_lading")
	ct.shipping_line = project.get("custom_shipping_line")
	ct.delivery_destination = _project_delivery_destination(project.name)
	if at_creation or not ct.get("eta"):
		ct.eta = project.get("custom_eta")
	project_ata = project.get("custom_ata")
	if project_ata and (at_creation or not ct.get("ata")):
		ct.ata = project_ata
	ct.container_mode = _derive_container_mode(project)
	if at_creation:
		populate_rates_from_shipping_line(ct, force=True)
		if ct.get("kpa_free_days") is None:
			ct.kpa_free_days = get_default_kpa_free_days()
	apply_metrics_to_doc(ct)


def create_or_sync_tracker_for_row(project, row) -> str:
	"""Create or reuse tracker by (project, container_number, type_of_container)."""
	existing_name = find_tracker_by_identity(
		project.name,
		row.container_number,
		row.get("type_of_container"),
	)
	if existing_name:
		ct = frappe.get_doc("Container Tracker", existing_name)
		_populate_tracker_from_project_and_row(ct, project, row)
		ct.save(ignore_permissions=True)
		_link_container_row(row, existing_name)
		return existing_name

	linked = _resolve_tracker_from_row_link(project.name, row)
	if linked:
		_populate_tracker_from_project_and_row(linked, project, row)
		linked.save(ignore_permissions=True)
		_link_container_row(row, linked.name)
		return linked.name

	ct = frappe.new_doc("Container Tracker")
	_populate_tracker_from_project_and_row(ct, project, row, at_creation=True)
	ct.insert(ignore_permissions=True)
	_link_container_row(row, ct.name)
	return ct.name


def create_container_trackers_for_project(project_name: str) -> list[str]:
	if not project_name or not frappe.db.exists("Project", project_name):
		return []

	project = frappe.get_doc("Project", project_name)
	container_field = get_container_table_field_for_doctype("Project")
	if not container_field:
		return []

	touched: list[str] = []
	for row in project.get(container_field) or []:
		if not row.get("container_number"):
			continue
		touched.append(create_or_sync_tracker_for_row(project, row))

	if touched:
		_link_bl_container_trackers(project)
		frappe.db.commit()
	return touched


def _trackers_for_project(project_name: str) -> list:
	names = frappe.get_all(
		"Container Tracker",
		filters={"project": project_name},
		pluck="name",
		order_by="container_number asc",
	)
	return [frappe.get_doc("Container Tracker", name) for name in names]


def _save_trackers(trackers: list) -> None:
	for ct in trackers:
		apply_metrics_to_doc(ct)
		ct.save(ignore_permissions=True)


def _save_tracker(ct) -> None:
	apply_metrics_to_doc(ct)
	ct.save(ignore_permissions=True)


def _apply_transport_from_task(ct, task_doc) -> None:
	if not task_doc:
		return
	meta = frappe.get_meta("Task")
	for ct_field, task_field in (
		("truck_number", "custom_truck_number"),
		("driver_name", "custom_driver_name"),
		("driver_contact", "custom_driver_contact"),
		("transporter", "custom_transporter"),
	):
		if meta.has_field(task_field) and task_doc.get(task_field):
			ct.set(ct_field, task_doc.get(task_field))


def _apply_bulk_eta(project, trackers: list) -> None:
	eta = project.get("custom_eta")
	if not eta or not trackers:
		return
	for ct in trackers:
		ct.eta = eta
	_save_trackers(trackers)


def _apply_bulk_vessel_arrival(project, trackers: list, today_date, task_doc=None) -> None:
	"""Task 11 — create trackers (vessel arrived); discharge dates come from task grid."""
	create_container_trackers_for_project(project.name)
	trackers = _trackers_for_project(project.name)
	ata = project.get("custom_ata")
	for ct in trackers:
		if ata:
			ct.ata = ata
	_save_trackers(trackers)

	if task_doc:
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
			apply_container_updates_from_task,
			seed_container_update_rows,
		)

		if seed_container_update_rows(task_doc):
			task_doc.save(ignore_permissions=True)
		apply_container_updates_from_task(task_doc)

	_notify_free_days_awareness(project.name)


def _notify_free_days_awareness(project_name: str) -> None:
	"""Warn ops when trackers were created without supplier free days."""
	trackers = frappe.get_all(
		"Container Tracker",
		filters={"project": project_name},
		fields=["name", "container_number", "free_days", "kpa_free_days", "shipping_line"],
	)
	if not trackers:
		return

	missing_free_days = [t.container_number for t in trackers if not t.free_days]
	message = (
		f"Container Trackers created for {len(trackers)} container(s) on {project_name}."
	)
	if missing_free_days:
		message += (
			f" FREE DAYS NOT SET for: {', '.join(missing_free_days)}. "
			"Enter free days from the shipping line guarantee form to track demurrage."
		)

	frappe.publish_realtime(
		"cgm_container_tracking_alert",
		{
			"project": project_name,
			"message": message,
			"type": "warning" if missing_free_days else "info",
		},
	)


def _apply_book_trucks_task(project, task_doc=None) -> None:
	"""Task 19 — fallback tracker creation; truck details from task grid."""
	if not _trackers_for_project(project.name):
		create_container_trackers_for_project(project.name)
	if task_doc:
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
			apply_container_updates_from_task,
		)

		apply_container_updates_from_task(task_doc)


def _apply_bulk_field_clearance(project, trackers: list) -> None:
	location = project.get("custom_final_destination") or project.get(
		"custom_clearance_station"
	)
	if not location or not trackers:
		return
	for ct in trackers:
		ct.current_location = location
	_save_trackers(trackers)


def _apply_bulk_kpa_paid(project, trackers: list, today_date) -> None:
	if not trackers:
		return
	release = project.get("custom_custom_release_date") or today_date
	for ct in trackers:
		ct.custom_release_date = release
	_save_trackers(trackers)


def _apply_gate_out(ct, today_date, task_doc) -> None:
	if not ct.gate_out_date_port:
		ct.gate_out_date_port = today_date
	_apply_transport_from_task(ct, task_doc)


def _apply_delivery(ct, today_date) -> None:
	if not ct.gate_in_date_warehouse:
		ct.gate_in_date_warehouse = today_date
	if not ct.delivery_date:
		ct.delivery_date = today_date


def _apply_offload(ct, today_date) -> None:
	if not ct.offloading_date:
		ct.offloading_date = today_date


def _apply_empty_return(ct, today_date) -> None:
	if not ct.actual_empty_return:
		ct.actual_empty_return = today_date
	if not ct.gate_in_date_depot:
		ct.gate_in_date_depot = today_date


def _apply_interchange(ct, today_date, task_doc) -> None:
	if not ct.interchange_date:
		ct.interchange_date = today_date
	if not ct.deposit_refund_status:
		ct.deposit_refund_status = DEPOSIT_REFUND_STATUSES[0]
	if task_doc:
		meta = frappe.get_meta("Task")
		if meta.has_field("custom_interchange_document") and task_doc.get(
			"custom_interchange_document"
		):
			ct.interchange_document = task_doc.custom_interchange_document


def _resolve_event_tracker(project_name: str, ctx: dict):
	"""Best-effort tracker resolution for a container-specific event.

	Returns None — so task completion is NOT blocked — when the project has no
	Container Tracker (e.g. LCL / consolidated cargo) or when the container is
	ambiguous and the task does not pin one. The ambiguous / lookup-failure cases
	show a non-blocking warning instead of throwing.
	"""
	container_tracker = ctx.get("container_tracker")
	container_number = ctx.get("container_number")
	if container_tracker or container_number:
		try:
			return resolve_single_tracker(
				project_name,
				container_tracker=container_tracker,
				container_number=container_number,
				type_of_container=ctx.get("type_of_container"),
			)
		except ContainerEventResolutionError as exc:
			frappe.msgprint(str(exc), indicator="orange", alert=True)
			return None

	trackers = _trackers_for_project(project_name)
	if not trackers:
		# No containers on this project (LCL / consolidated) — nothing to update.
		return None
	if len(trackers) == 1:
		# Unambiguous: use the project's sole container.
		return trackers[0]
	frappe.msgprint(
		_(
			"This task affects a single container but the project has multiple. "
			"Set <b>Container Tracker</b> or <b>Container Number</b> on the task to "
			"record this event on the right container."
		),
		indicator="orange",
		alert=True,
	)
	return None


def _apply_container_specific_event(
	seq: int,
	project_name: str,
	task_doc,
	today_date,
) -> None:
	ct = _resolve_event_tracker(project_name, _event_context_from_task(task_doc))
	if ct is None:
		return

	if seq == get_gate_out_task_sequence():
		_apply_gate_out(ct, today_date, task_doc)
	elif seq == get_container_task_sequence("custom_monitor_delivery_task_seq"):
		_apply_delivery(ct, today_date)
	elif seq == get_container_task_sequence("custom_offload_task_seq"):
		_apply_offload(ct, today_date)
	elif seq == get_empty_return_task_sequence():
		_apply_empty_return(ct, today_date)
	elif seq == get_container_task_sequence("custom_interchange_task_seq"):
		_apply_interchange(ct, today_date, task_doc)
	else:
		return

	_save_tracker(ct)


def handle_sea_task_container_event(
	project_name: str,
	seq: int,
	*,
	task_doc=None,
) -> None:
	if not project_name:
		return

	if is_container_specific_event(seq):
		if (
			task_doc
			and task_doc.meta.has_field("custom_container_updates")
			and task_doc.get("custom_container_updates")
		):
			return
		_apply_container_specific_event(seq, project_name, task_doc, getdate(today()))
		return

	if not is_bulk_container_event(seq):
		return

	project = frappe.get_cached_doc("Project", project_name)
	today_date = getdate(today())
	trackers = _trackers_for_project(project_name)

	if seq == get_container_task_sequence("custom_track_eta_task_seq"):
		_apply_bulk_eta(project, trackers)
	elif seq == get_container_task_sequence("custom_vessel_arrival_task_seq"):
		_apply_bulk_vessel_arrival(project, trackers, today_date, task_doc=task_doc)
	elif seq == get_container_task_sequence("custom_field_clearance_task_seq"):
		_apply_bulk_field_clearance(project, trackers)
	elif seq == get_container_task_sequence("custom_kpa_paid_task_seq"):
		_apply_bulk_kpa_paid(project, trackers, today_date)
	elif seq == get_container_task_sequence("custom_book_trucks_task_seq"):
		_apply_book_trucks_task(project, task_doc)


def on_gate_out(project_name: str, *, task_doc=None) -> None:
	handle_sea_task_container_event(
		project_name, get_gate_out_task_sequence(), task_doc=task_doc
	)


def on_empty_return(project_name: str, *, task_doc=None) -> None:
	handle_sea_task_container_event(
		project_name, get_empty_return_task_sequence(), task_doc=task_doc
	)


def get_containers_for_project(project_name: str) -> list[dict]:
	frappe.has_permission("Project", ptype="read", doc=project_name, throw=True)
	if not frappe.db.exists("DocType", "Container Tracker"):
		return []
	rows = frappe.get_all(
		"Container Tracker",
		filters={"project": project_name},
		order_by="container_number asc",
	)
	out: list[dict] = []
	for row in rows:
		data = frappe.get_doc("Container Tracker", row.name).as_dict()
		data.update(compute_container_metrics(data))
		out.append(data)
	return out


def get_overdue_containers(project_name: str) -> list[dict]:
	return [
		c
		for c in get_containers_for_project(project_name)
		if c.get("status") == CONTAINER_STATUS_RETURN_OVERDUE
		or (c.get("alert_status") or "").startswith("🚨")
	]


@frappe.whitelist()
def refresh_open_project_container_metrics() -> int:
	from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker import (
		refresh_open_container_metrics,
	)

	return refresh_open_container_metrics()
