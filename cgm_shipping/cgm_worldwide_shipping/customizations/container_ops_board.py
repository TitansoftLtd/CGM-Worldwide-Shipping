"""Container Ops Board — shared data for dashboard page and return tracker."""
from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
	bl_all_containers_returned,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	CLOSED_CONTAINER_STATUSES,
	compute_container_metrics,
	traffic_light_for_row,
	_effective_return_date,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
	display_ref_from_values,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates import (
	format_latest_update_summary,
	get_latest_updates_for_trackers,
	get_ops_updates,
	get_unread_update_count,
)
from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker import (
	_CONTAINER_TRACKER_FIELDS,
	container_tracker_query_fields,
	enrich_container_row,
)

OPEN_RETURN_STATUSES = frozenset(
	{
		"Released / In Transit",
		"At Warehouse",
		"Cargo Offloaded",
		"Return Overdue",
		"Empty Returned",
	}
)

_TRAFFIC_SORT = {"red": 0, "amber": 1, "grey": 2, "green": 3}

# Far-future ordinal so blank ETAs sort after every real date.
_MISSING_ETA_ORDINAL = 10**9


def _eta_sort_key(row: dict) -> tuple:
	"""Soonest ETA first; blank ETA last; traffic urgency as tiebreaker."""
	eta = row.get("eta")
	if eta:
		try:
			ordinal = getdate(eta).toordinal()
		except Exception:
			ordinal = _MISSING_ETA_ORDINAL
	else:
		ordinal = _MISSING_ETA_ORDINAL
	return (ordinal, row.get("sort_key", 9))

_STATUS_PILL = {
	"Pending Arrival": "muted",
	"Vessel Berthed": "info",
	"Discharged / At Port": "warning",
	"Released / In Transit": "primary",
	"At Warehouse": "primary",
	"Cargo Offloaded": "active",
	"Empty Returned": "success",
	"Return Overdue": "danger",
	"Interchange Received": "success",
}


def _parse_filters(filters) -> frappe._dict:
	"""Accept dict or JSON string from frappe.call (client may send "{}" as a string)."""
	if not filters:
		return frappe._dict()
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	if isinstance(filters, (list, tuple)):
		return frappe._dict()
	return frappe._dict(filters)


def _project_header_fields() -> list[str]:
	meta = frappe.get_meta("Project")
	fields = ["name", "project_name", "customer"]
	for fieldname in (
		"custom_project_reference",
		"custom_cgm_ref_no",
		"custom_batch_no",
		"custom_client_refrence_no",
		"custom_bill_of_lading",
		"custom_shipping_line",
		"custom_vessel",
		"custom_country_of_origin",
		"custom_clearance_station",
		"custom_eta",
		"custom_actual_time_of_arrival_ata",
		"custom_quantity",
		"custom_shipment_status",
	):
		if meta.has_field(fieldname):
			fields.append(fieldname)
	return fields


@frappe.request_cache
def _project_cache() -> dict[str, dict]:
	rows = frappe.get_all("Project", fields=_project_header_fields(), limit_page_length=0)
	return {row.name: row for row in rows}


@frappe.request_cache
def _transporter_names() -> dict[str, str]:
	if not frappe.db.exists("DocType", "Supplier"):
		return {}
	rows = frappe.get_all("Supplier", fields=["name", "supplier_name"], limit_page_length=0)
	return {r.name: r.supplier_name or r.name for r in rows}


def _customer_name(customer: str | None) -> str:
	if not customer:
		return ""
	return frappe.db.get_value("Customer", customer, "customer_name") or customer


def _station_label(row: dict) -> str:
	station = row.get("delivery_location") or row.get("custom_clearance_station")
	if not station:
		return ""
	if frappe.db.exists("Clearance Station", station):
		return frappe.db.get_value("Clearance Station", station, "cfs_name") or station
	return station


def _contact_display(row: dict) -> str:
	parts = []
	if row.get("driver_name"):
		parts.append(str(row["driver_name"]).strip())
	if row.get("driver_contact"):
		parts.append(str(row["driver_contact"]).strip())
	return " / ".join(parts)


def _build_row(row: dict, projects: dict[str, dict]) -> dict:
	enriched = enrich_container_row(dict(row))
	project_doc = projects.get(enriched.get("project")) or {}
	tl = traffic_light_for_row(enriched)
	actual_return = enriched.get("actual_empty_return")
	interchange = enriched.get("interchange_date")
	effective_return = _effective_return_date(actual_return, interchange)
	alert_status = compute_container_metrics(dict(row)).get("alert_status") or ""

	status = enriched.get("status") or ""
	container_status = enriched.get("current_location") or ""
	shipping_line_id = (
		enriched.get("shipping_line") or project_doc.get("custom_shipping_line") or ""
	)
	out = {
		"name": enriched.get("name"),
		"container_number": enriched.get("container_number"),
		"project": enriched.get("project"),
		"project_ref": display_ref_from_values(project_doc),
		"cgm_ref_no": project_doc.get("custom_cgm_ref_no") or "",
		"batch_no": project_doc.get("custom_batch_no") or "",
		"client_reference_no": project_doc.get("custom_client_refrence_no") or "",
		"customer": _customer_name(project_doc.get("customer")),
		"bl_number": enriched.get("bl_number") or project_doc.get("custom_bill_of_lading"),
		"shipping_line": _transporter_names().get(shipping_line_id, "") or shipping_line_id,
		"country_of_origin": project_doc.get("custom_country_of_origin") or "",
		"eta": project_doc.get("custom_eta"),
		"ata": project_doc.get("custom_actual_time_of_arrival_ata"),
		"vessel_name": project_doc.get("custom_vessel") or "",
		"deposit_amount": float(enriched.get("deposit_amount") or 0),
		"deposit_payment_status": enriched.get("deposit_payment_status") or "",
		"deposit_refund_status": enriched.get("deposit_refund_status") or "",
		"deposit_refund_display": enriched.get("deposit_refund_display") or "",
		"deposit_refund_display_tone": enriched.get("deposit_refund_display_tone") or "",
		"has_deposit": int(enriched.get("has_deposit") or 0),
		"remarks": alert_status or "",
		"operational_status": status,
		"container_status": container_status,
		"status": status,
		"status_pill": _STATUS_PILL.get(status, "muted"),
		"container_mode": enriched.get("container_mode"),
		"port_days_used": enriched.get("port_days_used") or 0,
		"days_outstanding": enriched.get("days_outstanding") or 0,
		"demurrage_days": enriched.get("demurrage_days") or 0,
		"free_days": enriched.get("free_days") or 0,
		"free_days_end_date": enriched.get("free_days_end_date"),
		"kpa_free_days": enriched.get("kpa_free_days") or 0,
		"kpa_free_days_end_date": enriched.get("kpa_free_days_end_date"),
		"expected_empty_return": enriched.get("expected_empty_return"),
		"actual_empty_return": actual_return,
		"interchange_date": interchange,
		"effective_return_date": effective_return,
		"gate_in_port": enriched.get("discharging_date"),
		"gate_out_date_port": enriched.get("gate_out_date_port"),
		"icd_gate_in_date": enriched.get("icd_gate_in_date"),
		"icd_gate_out_date": enriched.get("icd_gate_out_date"),
		"gate_in_date_warehouse": enriched.get("gate_in_date_warehouse"),
		"offloading_date": enriched.get("offloading_date"),
		"discharging_date": enriched.get("discharging_date"),
		"truck_number": enriched.get("truck_number") or "",
		"driver_name": enriched.get("driver_name") or "",
		"driver_contact": enriched.get("driver_contact") or "",
		"contact_display": _contact_display(enriched),
		"transporter": enriched.get("transporter") or "",
		"transporter_name": _transporter_names().get(enriched.get("transporter") or "", "")
		or enriched.get("transporter")
		or "",
		"clearance_station": _station_label(enriched)
		or _station_label(project_doc),
		"alert_status": alert_status,
		"traffic_light": tl.get("level"),
		"traffic_label": tl.get("label"),
		"traffic_css": tl.get("css"),
		"sort_key": _TRAFFIC_SORT.get(tl.get("level"), 9),
	}
	out["days_display"] = (
		out["days_outstanding"] if out["days_outstanding"] else out["port_days_used"]
	)
	return out


def _enrich_rows_with_transporter_updates(rows: list[dict]) -> list[dict]:
	tracker_names = [row.get("name") for row in rows if row.get("name")]
	latest = get_latest_updates_for_trackers(tracker_names)
	for row in rows:
		update = latest.get(row.get("name") or "") or {}
		row["last_transporter_update"] = format_latest_update_summary(update or None)
		row["last_transporter_update_type"] = (
			update.get("subject") or update.get("update_type") or ""
		)
		row["last_transporter_update_on"] = update.get("posted_on")
		row["last_transporter_update_message"] = update.get("message") or ""
	return rows


def _normalize_date_field(date_field: str | None) -> str | None:
	"""Map UI labels (ETA/ATA) and keys (eta/ata) to a canonical key."""
	if not date_field:
		return None
	key = str(date_field).strip().lower()
	if key in ("eta", "ata"):
		return key
	return None


def _list_filters(filters) -> dict:
	"""DB filters applied directly on Container Tracker.

	Customer / B/L / shipping-line fallback / date ranges that depend on Project
	are applied after fetch via post-filters — shipping_line and status that live
	on the tracker itself are applied here.
	"""
	list_filters: dict = {}
	if filters.get("project"):
		list_filters["project"] = filters.project
	if filters.get("status"):
		list_filters["status"] = filters.status
	if filters.get("container_mode"):
		list_filters["container_mode"] = filters.container_mode
	station = filters.get("clearance_station")
	if station:
		list_filters["delivery_location"] = station
	return list_filters


def _fetch_tracker_rows(filters) -> list[dict]:
	return frappe.get_list(
		"Container Tracker",
		filters=_list_filters(filters),
		fields=container_tracker_query_fields(),
		order_by="modified desc",
		limit_page_length=0,
	)


def _project_filters(filters) -> dict:
	project_filters: dict = {}
	if filters.get("customer"):
		project_filters["customer"] = filters.customer
	if filters.get("shipping_line"):
		project_filters["custom_shipping_line"] = filters.shipping_line
	if filters.get("status"):
		project_filters["custom_shipment_status"] = filters.status
	station = filters.get("clearance_station")
	if station:
		project_filters["custom_clearance_station"] = station
	if filters.get("bill_of_lading"):
		project_filters["custom_bill_of_lading"] = filters.bill_of_lading
	batch_no = (filters.get("batch_no") or "").strip()
	if batch_no:
		project_filters["custom_batch_no"] = ["like", f"%{batch_no}%"]
	date_key = _normalize_date_field(filters.get("date_field"))
	if date_key:
		field = (
			"custom_eta" if date_key == "eta" else "custom_actual_time_of_arrival_ata"
		)
		if filters.get("date_from") and filters.get("date_to"):
			project_filters[field] = ["between", [filters.date_from, filters.date_to]]
		elif filters.get("date_from"):
			project_filters[field] = [">=", filters.date_from]
		elif filters.get("date_to"):
			project_filters[field] = ["<=", filters.date_to]
	return project_filters


def _filter_by_shipping_line(
	rows: list[dict], shipping_line: str | None, projects: dict
) -> list[dict]:
	"""Match tracker.shipping_line or the parent project's custom_shipping_line."""
	if not shipping_line:
		return rows
	filtered = []
	for row in rows:
		tracker_line = (row.get("shipping_line") or "").strip()
		project_line = (
			(projects.get(row.get("project")) or {}).get("custom_shipping_line") or ""
		).strip()
		if shipping_line in (tracker_line, project_line):
			filtered.append(row)
	return filtered


def _filter_by_date_range(rows: list[dict], filters, projects: dict) -> list[dict]:
	"""Filter container rows by project ETA/ATA (same date field as Shipments tab)."""
	date_key = _normalize_date_field(filters.get("date_field"))
	if not date_key:
		return rows
	date_from = getdate(filters.date_from) if filters.get("date_from") else None
	date_to = getdate(filters.date_to) if filters.get("date_to") else None
	if not date_from and not date_to:
		return rows

	project_field = (
		"custom_eta" if date_key == "eta" else "custom_actual_time_of_arrival_ata"
	)
	filtered = []
	for row in rows:
		project_doc = projects.get(row.get("project")) or {}
		value = project_doc.get(project_field) or row.get(date_key)
		if not value:
			continue
		value = getdate(value)
		if date_from and value < date_from:
			continue
		if date_to and value > date_to:
			continue
		filtered.append(row)
	return filtered


def _apply_container_post_filters(
	rows: list[dict], filters, projects: dict
) -> list[dict]:
	"""Shared post-fetch filters for All Containers / Return Tracker tabs."""
	rows = _filter_by_customer(rows, filters.get("customer"), projects)
	rows = _filter_by_bill_of_lading(rows, filters.get("bill_of_lading"), projects)
	rows = _filter_by_batch_no(rows, filters.get("batch_no"), projects)
	rows = _filter_by_shipping_line(rows, filters.get("shipping_line"), projects)
	rows = _filter_by_date_range(rows, filters, projects)
	return rows


def _container_qty_size_from_trackers(rows: list[dict]) -> str | None:
	counts: dict[str, int] = {}
	for row in rows:
		cargo_size = (
			row.get("cargo_size") or row.get("cargo_type") or row.get("type_of_container") or ""
		).strip()
		if not cargo_size:
			continue
		counts[cargo_size] = counts.get(cargo_size, 0) + 1
	if not counts:
		return None
	dominant_size = max(counts, key=lambda key: (counts[key], key))
	qty = counts[dominant_size]
	size = re.sub(r"[^0-9]", "", dominant_size.upper()) or dominant_size.upper().replace("FT", "")
	return f"{qty}X{size}"


def _shipment_traffic_light(rows: list[dict]) -> dict[str, str]:
	if not rows:
		return {"level": "grey", "label": _("No Containers"), "css": "cgm-tl-grey"}
	levels = [r.get("traffic_light") for r in rows if r.get("traffic_light")]
	if "red" in levels:
		return {"level": "red", "label": _("ACTION NEEDED"), "css": "cgm-tl-red"}
	if "amber" in levels:
		return {"level": "amber", "label": _("AT RISK"), "css": "cgm-tl-amber"}
	if levels and all(level == "green" for level in levels):
		return {"level": "green", "label": _("CLEARED"), "css": "cgm-tl-green"}
	return {"level": "grey", "label": _("IN PROGRESS"), "css": "cgm-tl-grey"}


def _shipment_status_summary(rows: list[dict]) -> str:
	if not rows:
		return "No containers"
	returned = sum(1 for r in rows if r.get("status") in CLOSED_CONTAINER_STATUSES)
	overdue = sum(
		1
		for r in rows
		if r.get("status") == "Return Overdue"
		or (r.get("days_outstanding") or 0) > 0
	)
	demurrage = sum(
		1
		for r in rows
		if (r.get("demurrage_days") or 0) > 0 and r.get("status") not in CLOSED_CONTAINER_STATUSES
	)
	if returned == len(rows):
		return _("All {0} returned").format(returned)
	parts: list[str] = []
	if returned:
		parts.append(_("{0} returned").format(returned))
	if overdue:
		parts.append(_("{0} overdue").format(overdue))
	if demurrage:
		parts.append(_("{0} in demurrage").format(demurrage))
	if not parts:
		return _("{0} active").format(len(rows))
	return ", ".join(parts)


def _fetch_shipment_rows(filters) -> list[dict]:
	return frappe.get_all(
		"Project",
		filters=_project_filters(filters),
		fields=_project_header_fields(),
		order_by="custom_eta asc",
		limit_page_length=0,
	)


def _container_location_summary(rows: list[dict]) -> str:
	locations = [
		(r.get("container_status") or r.get("current_location") or "").strip()
		for r in rows
		if (r.get("container_status") or r.get("current_location") or "").strip()
	]
	if not locations:
		return _("No container location")
	unique = sorted(set(locations))
	if len(unique) == 1:
		return unique[0]
	if len(unique) <= 3:
		return ", ".join(unique)
	return _("{0} locations").format(len(unique))


COMPLETED_SHIPMENT_STATUSES = frozenset({"Completed", "Settled"})


def _is_in_demurrage(row: dict) -> bool:
	"""Active demurrage only — closed/returned containers are excluded from the KPI."""
	if row.get("status") in CLOSED_CONTAINER_STATUSES:
		return False
	return (row.get("demurrage_days") or 0) > 0


def _shipment_kpis(projects: list[dict], container_rows: list[dict]) -> dict:
	total = len(projects)
	completed = sum(
		1
		for project in projects
		if (project.get("custom_shipment_status") or "") in COMPLETED_SHIPMENT_STATUSES
	)
	active_shipments = total - completed
	return {
		"total_shipments": total,
		"active_shipments": active_shipments,
		"completed_shipments": completed,
		"overdue_returns": sum(1 for r in container_rows if _is_overdue_return(r)),
		"in_demurrage": sum(1 for r in container_rows if _is_in_demurrage(r)),
	}


def _latest_update_among(containers: list[dict]) -> dict | None:
	"""Most recent transporter update across a shipment's containers."""
	latest = None
	for row in containers:
		posted = row.get("last_transporter_update_on")
		if not posted:
			continue
		if latest is None or posted > latest.get("last_transporter_update_on"):
			latest = row
	return latest


def _build_shipment_row(project: dict, projects: dict[str, dict], container_rows: list[dict]) -> dict:
	supplier_label = _transporter_names().get(project.get("custom_shipping_line") or "") or (
		project.get("custom_shipping_line") or ""
	)
	containers = [
		row
		for row in container_rows
		if row.get("project") == project.get("name")
	]
	quantity = _container_qty_size_from_trackers(containers) or (project.get("custom_quantity") or "—")
	traffic = _shipment_traffic_light(containers)
	latest = _latest_update_among(containers)
	return {
		"name": project.get("name"),
		"project_ref": display_ref_from_values(project),
		"cgm_ref_no": project.get("custom_cgm_ref_no") or "",
		"customer": _customer_name(project.get("customer")),
		"bl_number": project.get("custom_bill_of_lading") or "",
		"batch_no": project.get("custom_batch_no") or "",
		"client_reference_no": project.get("custom_client_refrence_no") or "",
		"quantity": quantity,
		"shipping_line": supplier_label,
		"country_of_origin": project.get("custom_country_of_origin") or "",
		"eta": project.get("custom_eta"),
		"ata": project.get("custom_actual_time_of_arrival_ata"),
		"clearance_station": _station_label(project),
		"remarks": _shipment_status_summary(containers),
		"operational_status": project.get("custom_shipment_status") or "",
		"container_status_summary": _container_location_summary(containers),
		"shipment_status": project.get("custom_shipment_status") or "",
		"deposit_amount": _bl_deposit_amount_for_project(project),
		"deposit_payment_status": "",
		"deposit_refund_status": "",
		"deposit_refund_display": "",
		"deposit_refund_display_tone": "",
		"has_deposit": 0,
		"vessel_name": project.get("custom_vessel") or "",
		"traffic_light": traffic.get("level"),
		"traffic_label": traffic.get("label"),
		"traffic_css": traffic.get("css"),
		"sort_key": _TRAFFIC_SORT.get(traffic.get("level"), 9),
		"has_overdue": any(_is_overdue_return(c) for c in containers),
		"has_demurrage": any(_is_in_demurrage(c) for c in containers),
		"last_transporter_update": (latest or {}).get("last_transporter_update") or "",
		"last_transporter_update_type": (latest or {}).get("last_transporter_update_type") or "",
		"last_transporter_update_message": (latest or {}).get("last_transporter_update_message") or "",
		"last_transporter_update_on": (latest or {}).get("last_transporter_update_on"),
		"transporter_update_count": sum(
			1 for c in containers if c.get("last_transporter_update_type")
		),
	}


def _apply_shipment_kpi_filter(rows: list[dict], kpi_filter: str | None) -> list[dict]:
	if not kpi_filter:
		return rows
	if kpi_filter == "active_shipments":
		return [
			r
			for r in rows
			if (r.get("operational_status") or "") not in COMPLETED_SHIPMENT_STATUSES
		]
	if kpi_filter == "completed_shipments":
		return [
			r
			for r in rows
			if (r.get("operational_status") or "") in COMPLETED_SHIPMENT_STATUSES
		]
	if kpi_filter == "total_shipments":
		return rows
	if kpi_filter == "overdue_returns":
		return [r for r in rows if r.get("has_overdue")]
	if kpi_filter == "in_demurrage":
		return [r for r in rows if r.get("has_demurrage")]
	return rows


def _paginate_rows(rows: list[dict], filters) -> tuple[list[dict], int, int, int]:
	"""Slice rows for list-style pagination. KPIs stay based on the full filtered set."""
	total = len(rows)
	try:
		start = max(0, int(filters.get("start") or 0))
	except (TypeError, ValueError):
		start = 0
	try:
		page_length = int(filters.get("page_length") or 20)
	except (TypeError, ValueError):
		page_length = 20
	page_length = min(max(page_length, 1), 500)
	if start >= total and total > 0:
		start = (total - 1) // page_length * page_length
	return rows[start : start + page_length], total, start, page_length


@frappe.whitelist()
def get_shipment_tracker(filters=None) -> dict:
	frappe.has_permission("Container Tracker", ptype="read", throw=True)
	filters = _parse_filters(filters)
	# Status on the Shipments tab is shipment status — never pass it to tracker rows.
	projects = _fetch_shipment_rows(filters)
	project_map = {project["name"]: project for project in projects}
	tracker_rows = []
	if projects:
		tracker_rows = frappe.get_all(
			"Container Tracker",
			filters={"project": ["in", list(project_map)]},
			fields=container_tracker_query_fields(),
			order_by="modified desc",
			limit_page_length=0,
		)
	all_tracker_rows = _enrich_rows_with_transporter_updates(
		[_build_row(row, project_map) for row in tracker_rows]
	)
	all_tracker_rows = _enrich_ops_rows_with_bl_deposits(all_tracker_rows, project_map)
	kpis = _shipment_kpis(projects, all_tracker_rows)
	rows: list[dict] = []
	for project in projects:
		rows.append(_build_shipment_row(project, project_map, all_tracker_rows))
	rows = _enrich_ops_rows_with_bl_deposits(rows, project_map)
	rows = _apply_shipment_kpi_filter(rows, filters.get("kpi_filter"))
	rows.sort(key=_eta_sort_key)
	page_rows, total_count, start, page_length = _paginate_rows(rows, filters)
	return {
		"kpis": kpis,
		"rows": page_rows,
		"total_count": total_count,
		"start": start,
		"page_length": page_length,
		"kpi_filter": filters.get("kpi_filter"),
	}


@frappe.whitelist()
def get_project_containers_for_board(project: str) -> list[dict]:
	"""Container rows for one shipment — same shape as All Containers tab."""
	frappe.has_permission("Container Tracker", ptype="read", throw=True)
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	projects = _project_cache()
	raw = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=container_tracker_query_fields(),
		order_by="container_number asc",
		limit_page_length=0,
	)
	return _enrich_ops_rows_with_bl_deposits(
		_enrich_rows_with_transporter_updates(
			[_build_row(row, projects) for row in raw]
		),
		projects,
	)


def _filter_by_customer(rows: list[dict], customer: str | None, projects: dict) -> list[dict]:
	if not customer:
		return rows
	return [
		row
		for row in rows
		if (projects.get(row.get("project")) or {}).get("customer") == customer
	]


def _filter_by_bill_of_lading(
	rows: list[dict], bill_of_lading: str | None, projects: dict
) -> list[dict]:
	if not bill_of_lading:
		return rows
	bl_filter = bill_of_lading.strip().lower()
	if not bl_filter:
		return rows
	filtered = []
	for row in rows:
		project_doc = projects.get(row.get("project")) or {}
		bl_values = {
			(row.get("bl_number") or "").strip().lower(),
			(project_doc.get("custom_bill_of_lading") or "").strip().lower(),
		}
		bl_values.discard("")
		if any(bl_filter == value or bl_filter in value for value in bl_values):
			filtered.append(row)
	return filtered


def _filter_by_batch_no(
	rows: list[dict], batch_no: str | None, projects: dict
) -> list[dict]:
	if not batch_no:
		return rows
	batch_filter = str(batch_no).strip().lower()
	if not batch_filter:
		return rows
	filtered = []
	for row in rows:
		project_doc = projects.get(row.get("project")) or {}
		value = (project_doc.get("custom_batch_no") or "").strip().lower()
		if value and (batch_filter == value or batch_filter in value):
			filtered.append(row)
	return filtered


def _free_days_expiring(row: dict, ref) -> bool:
	free_end = row.get("free_days_end_date")
	if not free_end or row.get("gate_out_date_port"):
		return False
	if row.get("status") in CLOSED_CONTAINER_STATUSES:
		return False
	if row.get("actual_empty_return") or row.get("interchange_date"):
		return False
	remaining = (getdate(free_end) - ref).days
	return 0 <= remaining <= 2


def _returned_this_month(row: dict, month_start) -> bool:
	effective = row.get("effective_return_date")
	if not effective:
		return False
	return getdate(effective) >= month_start


def _is_overdue_return(row: dict) -> bool:
	if row.get("status") in CLOSED_CONTAINER_STATUSES:
		return False
	if (row.get("days_outstanding") or 0) > 0:
		return True
	if row.get("status") == "Return Overdue":
		return True
	alert = row.get("alert_status") or ""
	if "Late" in alert or "Overdue" in alert:
		return True
	if _is_in_demurrage(row):
		return True
	return False


def _bl_deposit_amount_for_project(project: dict) -> float:
	bl_name = (project.get("custom_bill_of_lading") or "").strip()
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return 0.0
	meta = frappe.get_meta("Bill of Lading")
	if not meta.has_field("deposit_amount"):
		return 0.0
	return flt(frappe.db.get_value("Bill of Lading", bl_name, "deposit_amount"))


def _load_bl_deposit_maps(projects: dict[str, dict]) -> tuple[dict, dict, dict]:
	"""Return (bl_by_name, child_by_tracker, child_by_bl_and_number)."""
	bl_names = {
		(p.get("custom_bill_of_lading") or "").strip()
		for p in projects.values()
		if (p.get("custom_bill_of_lading") or "").strip()
	}
	bl_names = {n for n in bl_names if frappe.db.exists("Bill of Lading", n)}
	if not bl_names:
		return {}, {}, {}

	meta = frappe.get_meta("Bill of Lading")
	if not meta.has_field("deposit_arrangement"):
		return {}, {}, {}

	fields = [
		"name",
		"deposit_arrangement",
		"deposit_payer",
		"deposit_amount",
		"deposit_payment_status",
		"deposit_refund_status",
		"deposit_return_date",
	]
	fields = [f for f in fields if meta.has_field(f) or f == "name"]
	bl_by_name = {
		r.name: r
		for r in frappe.get_all(
			"Bill of Lading", filters={"name": ["in", list(bl_names)]}, fields=fields
		)
	}
	child_by_tracker = {}
	child_by_bl_number = {}
	for row in frappe.get_all(
		"Container",
		filters={"parent": ["in", list(bl_names)], "parenttype": "Bill of Lading"},
		fields=[
			"parent",
			"container_number",
			"container_tracker",
			"deposit_amount",
		],
	):
		if row.container_tracker:
			child_by_tracker[row.container_tracker] = row
		key = (row.parent, (row.container_number or "").strip().upper())
		if key[1]:
			child_by_bl_number[key] = row
	return bl_by_name, child_by_tracker, child_by_bl_number


def _container_return_recorded(row: dict) -> bool:
	return bool(
		row.get("interchange_date")
		or row.get("actual_empty_return")
		or row.get("effective_return_date")
	)


def _deposit_refund_display(
	row: dict, bl: dict | None, bl_all_returned: bool, *, is_shipment_row: bool = False
) -> tuple[str, str]:
	"""Human label + pill tone for post-interchange deposit refund tracking."""
	has_deposit = float(row.get("deposit_amount") or 0) > 0 or cint(row.get("has_deposit"))
	if not has_deposit or not bl:
		return "", "muted"

	if (bl.get("deposit_arrangement") or "").strip() != "Container Deposit":
		return "", "muted"

	payer = (bl.get("deposit_payer") or "").strip()
	payment = (row.get("deposit_payment_status") or "").strip()
	refund = (row.get("deposit_refund_status") or "").strip()

	if payment != "Paid":
		return "", "muted"

	if payer == "Agent":
		return _("Agent Paid (no refund)"), "muted"

	if refund == "Received":
		return _("Refunded"), "success"
	if refund == "Forfeited":
		return _("Forfeited"), "muted"
	if refund == "Applied":
		return _("Applied"), "blue"
	if refund == "Pending":
		return _("Refund Pending"), "warning"

	if bl_all_returned:
		return _("Refund Pending"), "warning"

	if is_shipment_row:
		return _("Awaiting Return"), "muted"

	if _container_return_recorded(row):
		return _("Awaiting Other Containers"), "blue"

	return _("Awaiting Interchange"), "muted"


def _enrich_ops_rows_with_bl_deposits(rows: list[dict], projects: dict[str, dict]) -> list[dict]:
	"""Overlay BL deposit fields onto tracker/shipment rows (trackers no longer store deposits)."""
	bl_by_name, child_by_tracker, child_by_bl_number = _load_bl_deposit_maps(projects)
	bl_return_cache: dict[str, bool] = {}
	for bl_name in bl_by_name:
		all_returned, _return_date = bl_all_containers_returned(bl_name)
		bl_return_cache[bl_name] = all_returned

	if not bl_by_name:
		for row in rows:
			row.setdefault("has_deposit", 0)
			row.setdefault("deposit_amount", 0)
			row.setdefault("deposit_payment_status", "")
			row.setdefault("deposit_refund_status", "")
			row.setdefault("deposit_refund_display", "")
			row.setdefault("deposit_refund_display_tone", "")
		return rows

	for row in rows:
		project = projects.get(row.get("project") or row.get("name") or "") or {}
		# Shipment rows use project name as row.name
		bl_name = (
			(row.get("bl_number") or "").strip()
			or (project.get("custom_bill_of_lading") or "").strip()
		)
		bl = bl_by_name.get(bl_name)
		bl_all_returned = bl_return_cache.get(bl_name, False)
		if not bl or (bl.get("deposit_arrangement") or "").strip() != "Container Deposit":
			row["has_deposit"] = 0
			row["deposit_amount"] = 0
			row["deposit_payment_status"] = ""
			row["deposit_refund_status"] = ""
			row["deposit_refund_display"] = ""
			row["deposit_refund_display_tone"] = ""
			continue

		payer = (bl.get("deposit_payer") or "").strip()

		# Project/shipment card: BL totals
		if row.get("name") and row.get("name") == project.get("name"):
			row["has_deposit"] = 1
			row["deposit_amount"] = flt(bl.get("deposit_amount"))
			row["deposit_payment_status"] = (bl.get("deposit_payment_status") or "").strip()
			row["deposit_refund_status"] = (
				(bl.get("deposit_refund_status") or "").strip() if payer != "Agent" else ""
			)
			label, tone = _deposit_refund_display(
				row, bl, bl_all_returned, is_shipment_row=True
			)
			row["deposit_refund_display"] = label
			row["deposit_refund_display_tone"] = tone
			continue

		src = child_by_tracker.get(row.get("name"))
		if not src:
			src = child_by_bl_number.get(
				(bl_name, (row.get("container_number") or "").strip().upper())
			)
		amount = flt(src.get("deposit_amount")) if src else 0
		row["has_deposit"] = 1 if amount > 0 else 0
		row["deposit_amount"] = amount
		row["deposit_payment_status"] = (bl.get("deposit_payment_status") or "").strip() if amount > 0 else ""
		row["deposit_refund_status"] = (
			(bl.get("deposit_refund_status") or "").strip()
			if amount > 0 and payer != "Agent"
			else ""
		)
		label, tone = _deposit_refund_display(row, bl, bl_all_returned)
		row["deposit_refund_display"] = label if amount > 0 else ""
		row["deposit_refund_display_tone"] = tone if amount > 0 else ""
	return rows


def _bl_deposit_project_kpis(projects: dict[str, dict], rows: list[dict] | None = None) -> dict:
	"""Count distinct BLs (from filtered rows when provided) with unpaid / paid / refund-pending."""
	bl_by_name, _, _ = _load_bl_deposit_maps(projects)
	unpaid = paid = refund_pending = 0
	seen_bl = set()

	if rows is not None:
		bl_candidates = []
		for row in rows:
			bl_name = (row.get("bl_number") or "").strip()
			if not bl_name:
				proj = projects.get(row.get("project") or "") or {}
				bl_name = (proj.get("custom_bill_of_lading") or "").strip()
			if bl_name:
				bl_candidates.append(bl_name)
	else:
		bl_candidates = [
			(p.get("custom_bill_of_lading") or "").strip() for p in projects.values()
		]

	for bl_name in bl_candidates:
		if not bl_name or bl_name in seen_bl:
			continue
		bl = bl_by_name.get(bl_name)
		if not bl or (bl.get("deposit_arrangement") or "").strip() != "Container Deposit":
			continue
		seen_bl.add(bl_name)
		payment = (bl.get("deposit_payment_status") or "").strip()
		refund = (bl.get("deposit_refund_status") or "").strip()
		if payment == "Unpaid":
			unpaid += 1
		if payment == "Paid":
			paid += 1
		if refund == "Pending":
			refund_pending += 1
	return {
		"deposit_unpaid": unpaid,
		"deposit_paid": paid,
		"deposit_refund_pending": refund_pending,
	}


def _has_deposit(row: dict) -> bool:
	if row.get("has_deposit") is not None:
		return bool(cint(row.get("has_deposit")))
	return float(row.get("deposit_amount") or 0) > 0 and (
		row.get("deposit_payment_status") or ""
	) not in ("", "Not Applicable")


def _deposit_status(row: dict) -> str:
	return (row.get("deposit_payment_status") or "").strip()


def _deposit_refund_pending(row: dict) -> bool:
	if not _has_deposit(row):
		return False
	if _deposit_status(row) != "Paid":
		return False
	return (row.get("deposit_refund_status") or "").strip() == "Pending"


def _apply_kpi_filter(rows: list[dict], kpi_filter: str | None, ref) -> list[dict]:
	if not kpi_filter:
		return rows
	month_start = ref.replace(day=1)
	if kpi_filter == "total_active":
		return [r for r in rows if r.get("status") not in CLOSED_CONTAINER_STATUSES]
	if kpi_filter == "overdue_returns":
		return [r for r in rows if _is_overdue_return(r)]
	if kpi_filter == "in_demurrage":
		return [r for r in rows if _is_in_demurrage(r)]
	if kpi_filter == "free_days_expiring":
		return [r for r in rows if _free_days_expiring(r, ref)]
	if kpi_filter == "returned_this_month":
		return [r for r in rows if _returned_this_month(r, month_start)]
	if kpi_filter == "deposit_unpaid":
		return [r for r in rows if _has_deposit(r) and _deposit_status(r) == "Unpaid"]
	if kpi_filter == "deposit_paid":
		return [r for r in rows if _has_deposit(r) and _deposit_status(r) == "Paid"]
	if kpi_filter == "deposit_refund_pending":
		return [r for r in rows if _deposit_refund_pending(r)]
	return rows


def _kpis(rows: list[dict], projects: dict[str, dict] | None = None) -> dict:
	ref = getdate(today())
	month_start = ref.replace(day=1)
	active = [r for r in rows if r.get("status") not in CLOSED_CONTAINER_STATUSES]
	deposit_kpis = (
		_bl_deposit_project_kpis(projects, rows)
		if projects is not None
		else {
			"deposit_unpaid": sum(
				1 for r in rows if _has_deposit(r) and _deposit_status(r) == "Unpaid"
			),
			"deposit_paid": sum(
				1 for r in rows if _has_deposit(r) and _deposit_status(r) == "Paid"
			),
			"deposit_refund_pending": sum(1 for r in rows if _deposit_refund_pending(r)),
		}
	)
	return {
		"total_active": len(active),
		"overdue_returns": sum(1 for r in rows if _is_overdue_return(r)),
		"in_demurrage": sum(1 for r in rows if _is_in_demurrage(r)),
		"free_days_expiring": sum(1 for r in rows if _free_days_expiring(r, ref)),
		"returned_this_month": sum(1 for r in rows if _returned_this_month(r, month_start)),
		**deposit_kpis,
	}


def _is_return_tracker_row(row: dict, ref, month_start) -> bool:
	"""Post–gate-out containers: open returns, overdue, or returned recently."""
	if not row.get("gate_out_date_port"):
		return False
	if _is_overdue_return(row):
		return True
	if row.get("status") in OPEN_RETURN_STATUSES:
		return True
	if _returned_this_month(row, month_start):
		return True
	if (row.get("demurrage_days") or 0) > 0:
		return True
	return False


@frappe.whitelist()
def get_container_ops_board(filters=None) -> dict:
	frappe.has_permission("Container Tracker", ptype="read", throw=True)
	filters = _parse_filters(filters)
	projects = _project_cache()
	raw = _fetch_tracker_rows(filters)
	raw = _apply_container_post_filters(raw, filters, projects)
	all_rows = _enrich_rows_with_transporter_updates([_build_row(row, projects) for row in raw])
	all_rows = _enrich_ops_rows_with_bl_deposits(all_rows, projects)
	kpis = _kpis(all_rows, projects)

	rows = list(all_rows)
	if filters.get("traffic_light"):
		rows = [r for r in rows if r.get("traffic_light") == filters.traffic_light]
	rows = _apply_kpi_filter(rows, filters.get("kpi_filter"), getdate(today()))

	rows.sort(key=_eta_sort_key)
	page_rows, total_count, start, page_length = _paginate_rows(rows, filters)
	return {
		"kpis": kpis,
		"rows": page_rows,
		"total_count": total_count,
		"start": start,
		"page_length": page_length,
		"kpi_filter": filters.get("kpi_filter"),
	}


@frappe.whitelist()
def get_container_return_tracker(filters=None) -> dict:
	frappe.has_permission("Container Tracker", ptype="read", throw=True)
	filters = _parse_filters(filters)
	projects = _project_cache()
	ref = getdate(today())
	month_start = ref.replace(day=1)
	raw = _fetch_tracker_rows(filters)
	raw = _apply_container_post_filters(raw, filters, projects)

	pipeline_rows = _enrich_rows_with_transporter_updates(
		[
			built
			for built in (_build_row(row, projects) for row in raw)
			if _is_return_tracker_row(built, ref, month_start)
		]
	)
	pipeline_rows = _enrich_ops_rows_with_bl_deposits(pipeline_rows, projects)
	# KPIs always reflect the full return-pipeline under current filters (not the KPI drill-down).
	kpis = _kpis(pipeline_rows, projects)
	rows = _apply_kpi_filter(list(pipeline_rows), filters.get("kpi_filter"), ref)
	rows.sort(
		key=lambda r: (
			-(r.get("days_outstanding") or 0),
			-(r.get("demurrage_days") or 0),
			r.get("container_number") or "",
		)
	)
	page_rows, total_count, start, page_length = _paginate_rows(rows, filters)
	return {
		"rows": page_rows,
		"kpis": kpis,
		"count": total_count,
		"total_count": total_count,
		"start": start,
		"page_length": page_length,
		"kpi_filter": filters.get("kpi_filter"),
	}