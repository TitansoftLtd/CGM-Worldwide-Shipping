"""Container Tracker — per-container lifecycle engine (one tracker = one physical container)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from cgm_shipping.cgm_worldwide_shipping.customizations.container_charges import (
	compute_container_charge_amounts,
)
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
	DEPOSIT_PAYMENT_STATUSES,
	DEPOSIT_REFUND_STATUSES,
	TASK_CONTAINER_NUMBER_FIELD,
	TASK_CONTAINER_TRACKER_FIELD,
	TASK_CARGO_TYPE_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipping_line_rates import (
	default_destination_name,
	get_valid_destinations,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
	build_project_ata_updates,
	get_project_ata,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	container_row_cargo_size,
	tracker_cargo_size_field,
	tracker_row_cargo_size,
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
		settings = frappe.get_single("CGM Shipping Settings")
		if settings.meta.has_field(fieldname):
			configured = cint(settings.get(fieldname) or 0)
			if configured:
				return configured
	return default


def project_shipping_line_finance_paid(project: str | None) -> bool:
	"""True when the project's Shipping Line finance task is completed."""
	if not project:
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		shipping_line_finance_payment_sequences,
	)

	finance_seqs = shipping_line_finance_payment_sequences()
	if not finance_seqs:
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		task_flow_key_in_filter,
	)

	return bool(
		frappe.db.exists(
			"Task",
			{
				"project": project,
				"custom_task_flow_key": task_flow_key_in_filter(),
				"custom_sequence_no": ("in", list(finance_seqs)),
				"status": "Completed",
			},
		)
	)


def refresh_deposit_payment_status(ct) -> None:
	"""Derive deposit_payment_status from has_deposit + SL finance payment."""
	if not ct.meta.has_field("deposit_payment_status"):
		return
	has_deposit = cint(ct.get("has_deposit")) if ct.meta.has_field("has_deposit") else 0
	if not has_deposit:
		ct.deposit_payment_status = DEPOSIT_PAYMENT_STATUSES[0]  # Not Applicable
		return
	if project_shipping_line_finance_paid(ct.get("project")):
		ct.deposit_payment_status = DEPOSIT_PAYMENT_STATUSES[2]  # Paid
	else:
		ct.deposit_payment_status = DEPOSIT_PAYMENT_STATUSES[1]  # Unpaid


def sync_project_deposit_payment_statuses(project: str | None) -> int:
	"""Recompute deposit_payment_status on all trackers for a project. Returns updated count."""
	if not project or not frappe.db.exists("DocType", "Container Tracker"):
		return 0
	meta = frappe.get_meta("Container Tracker")
	if not meta.has_field("deposit_payment_status"):
		return 0
	updated = 0
	for name in frappe.get_all(
		"Container Tracker", filters={"project": project}, pluck="name"
	):
		ct = frappe.get_doc("Container Tracker", name)
		before = ct.get("deposit_payment_status")
		refresh_deposit_payment_status(ct)
		if ct.get("deposit_payment_status") != before:
			ct.db_set("deposit_payment_status", ct.deposit_payment_status, update_modified=False)
			updated += 1
	return updated


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


def _effective_return_date(actual_return, interchange):
	"""When the line return obligation is satisfied (interchange confirms closure)."""
	if interchange and actual_return:
		return max(interchange, actual_return)
	return interchange or actual_return


def _inclusive_days_between(start, end) -> int | None:
	start_date = _optional_date(start)
	end_date = _optional_date(end)
	if not start_date or not end_date:
		return None
	return max(0, (end_date - start_date).days + 1)


def _derived_free_days(data: dict[str, Any]) -> int:
	from_dates = _inclusive_days_between(
		data.get("free_days_start_date"), data.get("free_days_end_date")
	)
	if from_dates is not None:
		return from_dates
	return int(data.get("free_days") or 0)


def _derived_kpa_free_days(data: dict[str, Any]) -> int:
	from_dates = _inclusive_days_between(
		data.get("kpa_free_days_start_date"), data.get("kpa_free_days_end_date")
	)
	if from_dates is not None:
		return from_dates
	return int(data.get("kpa_free_days") or 0)


def _kpa_period_configured(data: dict[str, Any]) -> bool:
	return bool(
		data.get("kpa_free_days_start_date") and data.get("kpa_free_days_end_date")
	)


def sync_free_day_start_dates(doc) -> None:
	"""Default shipping-line and KPA free-day starts from discharge date when empty."""
	discharge = _optional_date(doc.get("discharging_date"))
	if not discharge:
		return
	if not doc.get("free_days_start_date"):
		doc.free_days_start_date = discharge
	if not doc.get("kpa_free_days_start_date"):
		doc.kpa_free_days_start_date = discharge


def _free_period_configured(data: dict[str, Any]) -> bool:
	return bool(data.get("free_days_start_date") and data.get("free_days_end_date"))


def populate_rates_from_shipping_line(doc, *, force: bool = False) -> None:
	"""Keep destination defaults only — free-day allowances come from tracker date ranges."""
	if doc.get("project") and not doc.get("delivery_destination"):
		doc.delivery_destination = _project_delivery_destination(doc.project)
	sync_free_day_start_dates(doc)


def _project_delivery_destination(project_name: str | None) -> str:
	if not project_name:
		return default_destination_name()
	meta = frappe.get_meta("Project")
	for fieldname in (
		"custom_destination_country",
		"custom_final_destination",
		"custom_delivery_destination",
	):
		if meta.has_field(fieldname):
			val = frappe.db.get_value("Project", project_name, fieldname)
			if val:
				return _normalize_destination(val)
	return default_destination_name()


_DESTINATION_ALIASES = {
	"ug": "Uganda",
	"ke": "Kenya",
	"tz": "Tanzania",
	"rw": "Rwanda",
	"kenya": "Kenya",
	"uganda": "Uganda",
	"tanzania": "Tanzania",
	"rwanda": "Rwanda",
}


def _normalize_destination(value: str) -> str:
	label = (value or "").strip()
	if not label:
		return default_destination_name()
	for dest in get_valid_destinations():
		if dest.lower() == label.lower():
			return dest
	mapped = _DESTINATION_ALIASES.get(label.lower())
	if mapped:
		for dest in get_valid_destinations():
			if dest.lower() == mapped.lower():
				return dest
	return default_destination_name()


def compute_container_metrics(data: dict[str, Any]) -> dict[str, Any]:
	ref_date = getdate(today())
	free_start = _optional_date(data.get("free_days_start_date"))
	free_end = _optional_date(data.get("free_days_end_date"))
	kpa_free_end = _optional_date(data.get("kpa_free_days_end_date"))
	gate_out = _optional_date(data.get("gate_out_date_port"))
	actual_return = _optional_date(data.get("actual_empty_return"))
	offloading = _optional_date(data.get("offloading_date"))
	gate_in_wh = _optional_date(data.get("gate_in_date_warehouse"))
	interchange = _optional_date(data.get("interchange_date"))
	discharging = _optional_date(data.get("discharging_date"))
	ata = _optional_date(data.get("ata"))

	free_days = _derived_free_days(data)
	kpa_free_days = _derived_kpa_free_days(data)
	free_configured = _free_period_configured(data)

	out: dict[str, Any] = {
		"free_days": free_days,
		"kpa_free_days": kpa_free_days,
		"port_days_used": 0,
		"demurrage_days": 0,
		"demurrage_amount": 0.0,
		"kpa_days": 0,
		"kpa_amount": 0.0,
		"expected_empty_return": free_end,
		"days_outstanding": 0,
		"status": CONTAINER_STATUS_PENDING_ARRIVAL,
		"alert_status": "",
	}

	if free_end:
		dem_start = free_end + timedelta(days=1)
		effective_return = _effective_return_date(actual_return, interchange)
		charge_end = effective_return or ref_date
		if charge_end >= dem_start:
			out["demurrage_days"] = (charge_end - dem_start).days + 1

	if free_start:
		end_port = gate_out or ref_date
		out["port_days_used"] = max(0, (end_port - free_start).days + 1)

	if kpa_free_end:
		kpa_charge_start = kpa_free_end + timedelta(days=1)
		kpa_charge_end = gate_out or ref_date
		if kpa_charge_end >= kpa_charge_start:
			out["kpa_days"] = (kpa_charge_end - kpa_charge_start).days + 1

	expected = _optional_date(out.get("expected_empty_return"))
	effective_return = _effective_return_date(actual_return, interchange)
	if expected and not effective_return and ref_date > expected:
		out["days_outstanding"] = (ref_date - expected).days

	out["status"] = _derive_tracker_status(data, ref_date=ref_date)
	out["alert_status"] = _derive_alert_status(
		free_end=free_end,
		free_start=free_start,
		gate_out=gate_out,
		actual_return=actual_return,
		interchange=interchange,
		expected_return=expected,
		ref_date=ref_date,
		free_configured=free_configured,
	)
	out.update(compute_container_charge_amounts(data, out))
	return out


_COMPUTED_ONLY_METRIC_FIELDS = frozenset({"alert_status"})


def apply_metrics_to_doc(doc) -> None:
	metrics = compute_container_metrics(doc.as_dict())
	for field, value in metrics.items():
		if field in _COMPUTED_ONLY_METRIC_FIELDS:
			continue
		setattr(doc, field, value)


def _derive_tracker_status(data: dict[str, Any], *, ref_date) -> str:
	mode = (data.get("container_mode") or "").strip()
	if mode and "Transit" in mode:
		return _derive_transit_status(data)
	return _derive_status(
		interchange=_optional_date(data.get("interchange_date")),
		actual_return=_optional_date(data.get("actual_empty_return")),
		expected_return=_optional_date(data.get("expected_empty_return")),
		offloading=_optional_date(data.get("offloading_date")),
		gate_in_wh=_optional_date(data.get("gate_in_date_warehouse")),
		gate_out=_optional_date(data.get("gate_out_date_port")),
		discharging=_optional_date(data.get("discharging_date")),
		ata=_optional_date(data.get("ata")),
		ref_date=ref_date,
	)


def _derive_transit_status(data: dict[str, Any]) -> str:
	mode = data.get("container_mode") or ""
	is_outbound = "Export" in mode

	if data.get("offloading_date"):
		return "Offloaded at Destination"
	if data.get("gate_in_date_warehouse"):
		return "Arrived at Destination"
	if data.get("border_clearance_date"):
		return "Border Cleared"
	if data.get("transit_departure_date"):
		return "In Transit"
	if data.get("ecmd_fitted_date"):
		return "Departed / ECMD Active"
	if data.get("c2_number"):
		return "C2 Obtained"
	if data.get("delivery_note_number"):
		return "Delivery Note Ready"
	if data.get("loading_slip_number"):
		return "Loading Slip Received"
	if data.get("release_order_number"):
		return "Release Order Obtained"

	if is_outbound:
		if data.get("warehouse_loading_date"):
			return "Loading at Warehouse"
		return "Pending Loading"

	if data.get("gate_out_date_port"):
		return "Released from Port"
	if data.get("custom_release_date"):
		return "KRA Released"
	if data.get("discharging_date"):
		return "Discharged / At Port"
	if data.get("ata"):
		return "Vessel Berthed"
	return "Pending Arrival"


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
	free_end,
	free_start,
	gate_out,
	actual_return,
	interchange,
	expected_return,
	ref_date,
	free_configured=True,
) -> str:
	"""Urgency overlay on operational status. Not stored in DB."""
	if free_configured and free_end and not gate_out:
		if ref_date > free_end:
			overdue = (ref_date - free_end).days
			return f"🔴 Demurrage Accruing ({overdue} day(s) past free period)"
		days_remaining = (free_end - ref_date).days
		if 0 <= days_remaining <= 2:
			return "⚠️ Free Days Expiring Soon"

	effective_return = _effective_return_date(actual_return, interchange)

	if not effective_return and expected_return:
		if ref_date > expected_return:
			overdue_days = (ref_date - expected_return).days
			return f"🚨 Return Overdue ({overdue_days} days)"
		days_to_return = (expected_return - ref_date).days
		if 0 <= days_to_return <= 2:
			return f"⚠️ Return Due in {days_to_return} days"

	if effective_return and expected_return:
		if effective_return <= expected_return:
			return "✅ Returned On Time"
		late_days = (effective_return - expected_return).days
		return f"⚠️ Returned Late ({late_days} day(s) past free period)"

	return ""


def _derive_container_mode(project) -> str:
	for fieldname in ("custom_container_tracker_mode", "project_type"):
		value = (project.get(fieldname) or "").strip()
		if value:
			return value

	if project.name:
		for fieldname in ("custom_container_tracker_mode", "project_type"):
			value = frappe.db.get_value("Project", project.name, fieldname) or ""
			if str(value).strip():
				return str(value).strip()

	return "Mombasa Port"


def find_tracker_by_identity(
	project_name: str,
	container_number: str,
	cargo_size: str | None = None,
) -> str | None:
	if not project_name or not container_number:
		return None
	size_field = tracker_cargo_size_field()
	filters: dict[str, Any] = {
		"project": project_name,
		"container_number": container_number,
	}
	if cargo_size:
		filters[size_field] = cargo_size
	return frappe.db.get_value("Container Tracker", filters, "name")


def _container_identity_filters(
	project_name: str,
	container_number: str,
	cargo_size: str | None,
) -> dict[str, Any]:
	size_field = tracker_cargo_size_field()
	filters: dict[str, Any] = {
		"project": project_name,
		"container_number": container_number,
	}
	if cargo_size:
		filters[size_field] = cargo_size
	return filters


def resolve_single_tracker(
	project_name: str,
	*,
	container_tracker: str | None = None,
	container_number: str | None = None,
	cargo_size: str | None = None,
	cargo_type: str | None = None,
) -> frappe.Document:
	"""Resolve exactly one Container Tracker for a container-specific lifecycle event."""
	cargo_size = cargo_size or cargo_type
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
				"or <b>Container Number</b> (+ Cargo Type when required) on the Task."
			),
			ContainerEventResolutionError,
		)

	filters = _container_identity_filters(
		project_name, container_number, cargo_size
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
				"Set <b>Cargo Size</b> or link the exact <b>Container Tracker</b>."
			).format(container_number),
			ContainerEventResolutionError,
		)

	if not cargo_size:
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
					"Set <b>Cargo Size</b> or link the exact <b>Container Tracker</b>."
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
		"cargo_type": task_doc.get(TASK_CARGO_TYPE_FIELD),
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
		and tracker_row_cargo_size(ct) == container_row_cargo_size(row)
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
		fields=["name", "container_number", "cargo_size", "type_of_container"],
	):
		if not row.container_number:
			continue
		tracker_name = find_tracker_by_identity(
			project.name, row.container_number, container_row_cargo_size(row)
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
	size_field = tracker_cargo_size_field()
	ct.project = project.name
	ct.container_number = row.container_number
	ct.set(size_field, container_row_cargo_size(row))
	ct.seal_no = row.get("seal_no")
	ct.bl_number = project.get("custom_bill_of_lading")
	ct.shipping_line = project.get("custom_shipping_line")
	ct.delivery_destination = _project_delivery_destination(project.name)
	if at_creation or not ct.get("eta"):
		ct.eta = project.get("custom_eta")
	project_ata = get_project_ata(project)
	if project_ata and (at_creation or not ct.get("ata")):
		ct.ata = project_ata
	ct.container_mode = _derive_container_mode(project)
	if at_creation:
		populate_rates_from_shipping_line(ct, force=True)
		_default_kpa_free_end_from_settings(ct)
	apply_metrics_to_doc(ct)


def _default_kpa_free_end_from_settings(doc) -> None:
	"""Seed KPA free end from CGM Shipping Settings when only the start date is known."""
	if doc.get("kpa_free_days_end_date") or not doc.get("kpa_free_days_start_date"):
		return
	allowance = get_default_kpa_free_days()
	if allowance <= 0:
		return
	start = getdate(doc.kpa_free_days_start_date)
	doc.kpa_free_days_end_date = start + timedelta(days=allowance - 1)


def create_or_sync_tracker_for_row(project, row) -> str:
	"""Create or reuse tracker by (project, container_number, cargo_size)."""
	row_size = container_row_cargo_size(row)
	existing_name = find_tracker_by_identity(
		project.name,
		row.container_number,
		row_size,
	)
	if existing_name:
		ct = frappe.get_doc("Container Tracker", existing_name)
		_populate_tracker_from_project_and_row(ct, project, row)
		ct.save(ignore_permissions=True)
		_link_container_row(row, existing_name)
		_ensure_seal_record_for_tracker_row(project.name, row, existing_name)
		return existing_name

	linked = _resolve_tracker_from_row_link(project.name, row)
	if linked:
		_populate_tracker_from_project_and_row(linked, project, row)
		linked.save(ignore_permissions=True)
		_link_container_row(row, linked.name)
		_ensure_seal_record_for_tracker_row(project.name, row, linked.name)
		return linked.name

	ct = frappe.new_doc("Container Tracker")
	_populate_tracker_from_project_and_row(ct, project, row, at_creation=True)
	ct.insert(ignore_permissions=True)
	_link_container_row(row, ct.name)
	_ensure_seal_record_for_tracker_row(project.name, row, ct.name)
	return ct.name


def _ensure_seal_record_for_tracker_row(project_name: str, row, tracker_name: str) -> None:
	"""Create/update Seal Record when a container row carries a seal number."""
	seal_no = (row.get("seal_no") or "").strip()
	if not seal_no:
		return
	from cgm_shipping.cgm_worldwide_shipping.doctype.seal_record.seal_record import (
		ensure_seal_record_for_container,
	)

	tracker = frappe.db.get_value(
		"Container Tracker",
		tracker_name,
		["new_seal_number", "reason_for_new_seal_number"],
		as_dict=True,
	)
	ensure_seal_record_for_container(
		project_name,
		seal_no,
		tracker_name,
		new_seal_number=(tracker.new_seal_number if tracker else "") or "",
		reason_for_new_seal_number=(tracker.reason_for_new_seal_number if tracker else "") or "",
	)


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
	ata = get_project_ata(project)
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

	missing_free_days = [
		t.container_number
		for t in trackers
		if not frappe.db.get_value(
			"Container Tracker",
			t.name,
			"free_days_end_date",
		)
	]
	message = (
		f"Container Trackers created for {len(trackers)} container(s) on {project_name}."
	)
	if missing_free_days:
		message += (
			f" Free days not recorded yet for: {', '.join(missing_free_days)}. "
			"Enter Shipping Line and KPA free-day end dates on each tracker after discharge."
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
	location = (
		project.get("custom_destination_country")
		or project.get("custom_final_destination")
		or project.get("custom_clearance_station")
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
				cargo_type=ctx.get("cargo_type"),
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

	project = frappe.get_doc("Project", project_name)
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


def _project_container_rows(project) -> list:
	container_field = get_container_table_field_for_doctype("Project")
	if not container_field:
		return []
	return [
		row
		for row in project.get(container_field) or []
		if (row.get("container_number") or "").strip()
	]


def ensure_container_trackers_at_port_arrival(
	project_name: str,
	*,
	task_doc=None,
	mark_confirmed: bool = False,
	user: str | None = None,
	ata=None,
) -> dict:
	"""Create/sync container trackers when shipment arrives at port (early or on Entry task)."""
	frappe.has_permission("Project", ptype="write", doc=project_name, throw=True)
	if not frappe.db.exists("Project", project_name):
		frappe.throw(_("Project not found"))

	project = frappe.get_doc("Project", project_name)
	if project.get("custom_mode_of_transport") != "Sea":
		frappe.throw(_("Container tracking at port arrival applies to Sea shipments only."))

	if not _project_container_rows(project):
		frappe.throw(_("Add containers on the project before creating container trackers."))

	updates: dict[str, Any] = {}
	if ata:
		updates.update(build_project_ata_updates(project, ata))
	elif not get_project_ata(project):
		updates.update(build_project_ata_updates(project, getdate(today())))

	if mark_confirmed and project.meta.has_field("custom_port_arrival_confirmed"):
		if not project.get("custom_port_arrival_confirmed"):
			updates["custom_port_arrival_confirmed"] = 1
			updates["custom_port_arrival_confirmed_on"] = frappe.utils.now_datetime()
			updates["custom_port_arrival_confirmed_by"] = user or frappe.session.user

	if project.meta.has_field("custom_berth_phase"):
		updates["custom_berth_phase"] = "After Vessel Berthed"

	if updates:
		frappe.db.set_value("Project", project_name, updates, update_modified=True)
		frappe.clear_document_cache("Project", project_name)
		project = frappe.get_doc("Project", project_name)

	seq = get_container_task_sequence("custom_vessel_arrival_task_seq")
	handle_sea_task_container_event(project_name, seq, task_doc=task_doc)

	trackers = frappe.get_all(
		"Container Tracker",
		filters={"project": project_name},
		pluck="name",
	)
	frappe.publish_realtime("cgm_project_tracking_refresh", {"project": project_name})

	return {
		"ok": True,
		"trackers": trackers,
		"tracker_count": len(trackers),
		"port_arrival_confirmed": bool(
			project.get("custom_port_arrival_confirmed") or mark_confirmed
		),
		"ata": str(get_project_ata(project) or ""),
	}


def ensure_container_trackers_on_entry_task_complete(task_doc) -> dict | None:
	"""Fallback when Create Entry completes without an early port-arrival confirmation."""
	project_name = task_doc.get("project")
	if not project_name:
		return None

	project = frappe.get_cached_doc("Project", project_name)
	if project.get("custom_port_arrival_confirmed"):
		return None
	if _trackers_for_project(project_name):
		return None

	return ensure_container_trackers_at_port_arrival(
		project_name,
		task_doc=task_doc,
		mark_confirmed=False,
	)


CLOSED_CONTAINER_STATUSES = (
	CONTAINER_STATUS_EMPTY_RETURNED,
	CONTAINER_STATUS_INTERCHANGE,
)


def traffic_light_for_row(row: dict[str, Any]) -> dict[str, str]:
	"""Return traffic-light label + CSS class for dashboard/report rows."""
	metrics = {**dict(row), **compute_container_metrics(dict(row))}
	status = metrics.get("status") or ""
	dem = int(metrics.get("demurrage_days") or 0)
	overdue = int(metrics.get("days_outstanding") or 0)
	ref_date = getdate(today())
	free_end = _optional_date(metrics.get("free_days_end_date"))
	expected = _optional_date(metrics.get("expected_empty_return"))

	if status in CLOSED_CONTAINER_STATUSES:
		return {"level": "green", "label": _("CLEARED"), "css": "cgm-tl-green"}

	if dem > 0 or overdue > 0:
		return {
			"level": "red",
			"label": _("NOT RELEASED / ACTION NEEDED"),
			"css": "cgm-tl-red",
		}

	if free_end and not metrics.get("gate_out_date_port"):
		days_remaining = (free_end - ref_date).days
		if 0 < days_remaining <= 2:
			return {"level": "amber", "label": _("ALMOST DUE"), "css": "cgm-tl-amber"}

	if expected and not metrics.get("actual_empty_return"):
		days_to_return = (expected - ref_date).days
		if 0 <= days_to_return <= 2:
			return {"level": "amber", "label": _("ALMOST DUE"), "css": "cgm-tl-amber"}

	if status in (CONTAINER_STATUS_PENDING_ARRIVAL, CONTAINER_STATUS_VESSEL_BERTHED):
		return {"level": "grey", "label": _("AWAITING"), "css": "cgm-tl-grey"}

	return {"level": "grey", "label": _("AWAITING"), "css": "cgm-tl-grey"}


@frappe.whitelist()
def project_can_confirm_port_arrival(project: str) -> dict:
	"""Whether the Project Actions menu should offer port arrival confirmation."""
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	if not frappe.db.exists("Project", project):
		return {"can_confirm": False}

	doc = frappe.get_doc("Project", project)
	if (doc.get("custom_mode_of_transport") or "").strip() != "Sea":
		return {"can_confirm": False}
	if doc.get("custom_port_arrival_confirmed"):
		return {"can_confirm": False}
	if not _project_container_rows(doc):
		return {"can_confirm": False}
	return {"can_confirm": True}


@frappe.whitelist()
def confirm_shipment_arrival_at_port(project_name: str, ata: str | None = None) -> dict:
	"""Confirm shipment arrival at port and create container trackers before Entry is paid."""
	project = frappe.get_doc("Project", project_name)
	if project.get("custom_port_arrival_confirmed"):
		frappe.throw(_("Port arrival has already been confirmed for this project."))
	return ensure_container_trackers_at_port_arrival(
		project_name,
		mark_confirmed=True,
		ata=ata,
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


@frappe.whitelist()
def get_containers_for_project_whitelisted(project: str | None = None, project_name: str | None = None) -> list[dict]:
	"""Whitelisted API for desk pages (accepts project or project_name)."""
	target = project or project_name
	if not target:
		frappe.throw(_("Project is required."))
	return get_containers_for_project(target)


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
