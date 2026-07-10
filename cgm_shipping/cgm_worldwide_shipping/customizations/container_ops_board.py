"""Container Ops Board — shared data for dashboard page and return tracker."""
from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import getdate, today

from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	CLOSED_CONTAINER_STATUSES,
	compute_container_metrics,
	traffic_light_for_row,
	_effective_return_date,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
	display_ref_from_values,
)
from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker import (
	_CONTAINER_TRACKER_FIELDS,
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
	out = {
		"name": enriched.get("name"),
		"container_number": enriched.get("container_number"),
		"project": enriched.get("project"),
		"project_ref": display_ref_from_values(project_doc),
		"batch_no": project_doc.get("custom_batch_no") or "",
		"customer": _customer_name(project_doc.get("customer")),
		"bl_number": enriched.get("bl_number") or project_doc.get("custom_bill_of_lading"),
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
		"clearance_station": _station_label(enriched),
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


def _list_filters(filters) -> dict:
	list_filters: dict = {}
	if filters.get("project"):
		list_filters["project"] = filters.project
	if filters.get("shipping_line"):
		list_filters["shipping_line"] = filters.shipping_line
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
		fields=_CONTAINER_TRACKER_FIELDS,
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
	if filters.get("date_field") in ("eta", "ata"):
		field = (
			"custom_eta"
			if filters.date_field == "eta"
			else "custom_actual_time_of_arrival_ata"
		)
		if filters.get("date_from") and filters.get("date_to"):
			project_filters[field] = ["between", [filters.date_from, filters.date_to]]
		elif filters.get("date_from"):
			project_filters[field] = [">=", filters.date_from]
		elif filters.get("date_to"):
			project_filters[field] = ["<=", filters.date_to]
	return project_filters


def _container_qty_size_from_trackers(rows: list[dict]) -> str | None:
	counts: dict[str, int] = {}
	for row in rows:
		cargo_type = (row.get("cargo_type") or "").strip()
		if not cargo_type:
			continue
		counts[cargo_type] = counts.get(cargo_type, 0) + 1
	if not counts:
		return None
	dominant_type = max(counts, key=lambda key: (counts[key], key))
	qty = counts[dominant_type]
	size = re.sub(r"[^0-9]", "", dominant_type.upper()) or dominant_type.upper().replace("FT", "")
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
		order_by="modified desc",
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
		"in_demurrage": sum(
			1 for r in container_rows if (r.get("demurrage_days") or 0) > 0
		),
	}


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
	return {
		"name": project.get("name"),
		"project_ref": display_ref_from_values(project),
		"customer": _customer_name(project.get("customer")),
		"bl_number": project.get("custom_bill_of_lading") or "",
		"batch_no": project.get("custom_batch_no") or "",
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
		"deposit_amount": float(
			frappe.db.sql(
				"SELECT SUM(deposit_amount) FROM `tabContainer Tracker` WHERE project=%s",
				(project.get("name"),),
				as_list=True,
			)[0][0] or 0
		),
		"vessel_name": project.get("custom_vessel") or "",
		"traffic_light": traffic.get("level"),
		"traffic_label": traffic.get("label"),
		"traffic_css": traffic.get("css"),
		"sort_key": _TRAFFIC_SORT.get(traffic.get("level"), 9),
		"has_overdue": any(_is_overdue_return(c) for c in containers),
		"has_demurrage": any(
			(c.get("demurrage_days") or 0) > 0 and c.get("status") not in CLOSED_CONTAINER_STATUSES
			for c in containers
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


@frappe.whitelist()
def get_shipment_tracker(filters=None) -> dict:
	frappe.has_permission("Container Tracker", ptype="read", throw=True)
	filters = _parse_filters(filters)
	projects = _fetch_shipment_rows(filters)
	project_map = {project["name"]: project for project in projects}
	tracker_rows = []
	if projects:
		tracker_rows = frappe.get_all(
			"Container Tracker",
			filters={"project": ["in", list(project_map)]},
			fields=_CONTAINER_TRACKER_FIELDS,
			order_by="modified desc",
			limit_page_length=0,
		)
	all_tracker_rows = [_build_row(row, project_map) for row in tracker_rows]
	kpis = _shipment_kpis(projects, all_tracker_rows)
	rows: list[dict] = []
	for project in projects:
		rows.append(_build_shipment_row(project, project_map, all_tracker_rows))
	rows = _apply_shipment_kpi_filter(rows, filters.get("kpi_filter"))
	rows.sort(key=lambda r: (r.get("sort_key", 9), -(r.get("deposit_amount") or 0)))
	return {"kpis": kpis, "rows": rows, "kpi_filter": filters.get("kpi_filter")}


@frappe.whitelist()
def get_project_containers_for_board(project: str) -> list[dict]:
	"""Container rows for one shipment — same shape as All Containers tab."""
	frappe.has_permission("Container Tracker", ptype="read", throw=True)
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	projects = _project_cache()
	raw = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=_CONTAINER_TRACKER_FIELDS,
		order_by="container_number asc",
		limit_page_length=0,
	)
	return [_build_row(row, projects) for row in raw]


def _filter_by_customer(rows: list[dict], customer: str | None, projects: dict) -> list[dict]:
	if not customer:
		return rows
	return [
		row
		for row in rows
		if (projects.get(row.get("project")) or {}).get("customer") == customer
	]


def _free_days_expiring(row: dict, ref) -> bool:
	free_end = row.get("free_days_end_date")
	if not free_end or row.get("gate_out_date_port"):
		return False
	remaining = (getdate(free_end) - ref).days
	return 0 <= remaining <= 2


def _returned_this_month(row: dict, month_start) -> bool:
	effective = row.get("effective_return_date")
	if not effective:
		return False
	return getdate(effective) >= month_start


def _is_overdue_return(row: dict) -> bool:
	if (row.get("days_outstanding") or 0) > 0:
		return True
	if row.get("status") == "Return Overdue":
		return True
	alert = row.get("alert_status") or ""
	if "Late" in alert or "Overdue" in alert:
		return True
	if (row.get("demurrage_days") or 0) > 0 and row.get("status") not in CLOSED_CONTAINER_STATUSES:
		return True
	return False


def _apply_kpi_filter(rows: list[dict], kpi_filter: str | None, ref) -> list[dict]:
	if not kpi_filter:
		return rows
	month_start = ref.replace(day=1)
	if kpi_filter == "total_active":
		return [r for r in rows if r.get("status") not in CLOSED_CONTAINER_STATUSES]
	if kpi_filter == "overdue_returns":
		return [r for r in rows if _is_overdue_return(r)]
	if kpi_filter == "in_demurrage":
		return [r for r in rows if (r.get("demurrage_days") or 0) > 0]
	if kpi_filter == "free_days_expiring":
		return [r for r in rows if _free_days_expiring(r, ref)]
	if kpi_filter == "returned_this_month":
		return [r for r in rows if _returned_this_month(r, month_start)]
	return rows


def _kpis(rows: list[dict]) -> dict:
	ref = getdate(today())
	month_start = ref.replace(day=1)
	active = [r for r in rows if r.get("status") not in CLOSED_CONTAINER_STATUSES]
	return {
		"total_active": len(active),
		"overdue_returns": sum(1 for r in rows if _is_overdue_return(r)),
		"in_demurrage": sum(1 for r in rows if (r.get("demurrage_days") or 0) > 0),
		"free_days_expiring": sum(1 for r in rows if _free_days_expiring(r, ref)),
		"returned_this_month": sum(1 for r in rows if _returned_this_month(r, month_start)),
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
	raw = _filter_by_customer(raw, filters.get("customer"), projects)
	all_rows = [_build_row(row, projects) for row in raw]
	kpis = _kpis(all_rows)

	rows = list(all_rows)
	if filters.get("traffic_light"):
		rows = [r for r in rows if r.get("traffic_light") == filters.traffic_light]
	rows = _apply_kpi_filter(rows, filters.get("kpi_filter"), getdate(today()))

	rows.sort(key=lambda r: (r.get("sort_key", 9), -(r.get("days_display") or 0)))
	return {"kpis": kpis, "rows": rows, "kpi_filter": filters.get("kpi_filter")}


@frappe.whitelist()
def get_container_return_tracker(filters=None) -> dict:
	frappe.has_permission("Container Tracker", ptype="read", throw=True)
	filters = _parse_filters(filters)
	projects = _project_cache()
	ref = getdate(today())
	month_start = ref.replace(day=1)
	raw = _fetch_tracker_rows(filters)
	raw = _filter_by_customer(raw, filters.get("customer"), projects)
	rows = []
	for row in raw:
		built = _build_row(row, projects)
		if not _is_return_tracker_row(built, ref, month_start):
			continue
		rows.append(built)

	all_rows = [_build_row(row, projects) for row in raw]
	kpis = _kpis(all_rows)

	rows = _apply_kpi_filter(rows, filters.get("kpi_filter"), ref)
	rows.sort(
		key=lambda r: (
			-(r.get("days_outstanding") or 0),
			-(r.get("demurrage_days") or 0),
			r.get("container_number") or "",
		)
	)
	return {"rows": rows, "kpis": kpis, "count": len(rows), "kpi_filter": filters.get("kpi_filter")}
