# Copyright (c) 2026, Titansoft Limited and contributors

from __future__ import annotations

import frappe
from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.customizations.container_charges import (
	refresh_project_charge_totals,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	CLOSED_CONTAINER_STATUSES,
	compute_container_metrics,
	populate_rates_from_shipping_line,
	refresh_deposit_payment_status,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	container_row_cargo_size,
	tracker_cargo_size_field,
	tracker_row_cargo_size,
)
from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_charges import (
	apply_metrics_to_doc,
)


class ContainerTracker(Document):
	def validate(self):
		refresh_deposit_payment_status(self)
		populate_rates_from_shipping_line(self)
		apply_metrics_to_doc(self)

	def on_update(self):
		sync_container_summary_to_project(self.project)
		_sync_project_child_row(self)
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_container_updates import (
			check_all_container_tasks_for_project,
			sync_tracker_fields_to_open_task_rows,
		)

		sync_tracker_fields_to_open_task_rows(self)
		check_all_container_tasks_for_project(self.project)


def _sync_project_child_row(doc) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_container_table_field_for_doctype,
	)

	container_field = get_container_table_field_for_doctype("Project")
	if not container_field or not doc.project:
		return

	child_rows = frappe.get_all(
		"Container",
		filters={
			"parent": doc.project,
			"parenttype": "Project",
			"parentfield": container_field,
		},
		fields=["name", "container_tracker", "container_number", "cargo_size", "type_of_container"],
	)
	tracker_size = tracker_row_cargo_size(doc)

	for row in child_rows:
		row_size = container_row_cargo_size(row)
		matched = row.container_tracker == doc.name or (
			row.container_number == doc.container_number
			and row_size == tracker_size
		)
		if not matched:
			continue

		child_updates = {
			"container_tracker": doc.name,
			"status": doc.status or "",
			"demurrage_days": doc.demurrage_days or 0,
		}
		container_meta = frappe.get_meta("Container")
		if container_meta.has_field("kpa_days"):
			child_updates["kpa_days"] = doc.kpa_days or 0
		if container_meta.has_field("demurrage_amount"):
			child_updates["demurrage_amount"] = doc.demurrage_amount or 0
		if container_meta.has_field("kpa_amount"):
			child_updates["kpa_amount"] = doc.kpa_amount or 0
		frappe.db.set_value("Container", row.name, child_updates, update_modified=False)
		break


_CONTAINER_TRACKER_FIELDS = [
	"name",
	"project",
	"container_number",
	"bl_number",
	"container_mode",
	tracker_cargo_size_field(),
	"seal_no",
	"shipping_line",
	"delivery_destination",
	"delivery_location",
	"eta",
	"ata",
	"discharging_date",
	"custom_release_date",
	"gate_out_date_port",
	"free_days_start_date",
	"free_days_end_date",
	"kpa_free_days_start_date",
	"kpa_free_days_end_date",
	"free_days",
	"kpa_free_days",
	"demurrage_daily_rate",
	"detention_daily_rate",
	"kpa_daily_rate",
	"free_days_count_from",
	"deposit_amount",
	"deposit_payment_status",
	"has_deposit",
	"icd_mombasa_discharge_date",
	"icd_gate_in_date",
	"icd_gate_out_date",
	"gate_in_date_warehouse",
	"offloading_date",
	"delivery_date",
	"warehouse_loading_date",
	"border_clearance_date",
	"transit_gate_in_date",
	"transit_gate_out_date",
	"truck_number",
	"driver_name",
	"driver_contact",
	"transporter",
	"port_days_used",
	"demurrage_days",
	"kpa_days",
	"demurrage_rate_currency",
	"demurrage_amount",
	"demurrage_amount_adjustment",
	"demurrage_amount_posted_to_je",
	"kpa_port_daily_rate",
	"kpa_rate_currency",
	"kpa_amount",
	"kpa_amount_adjustment",
	"kpa_amount_posted_to_je",
	"expected_empty_return",
	"actual_empty_return",
	"gate_in_date_depot",
	"interchange_date",
	"days_outstanding",
	"status",
	"current_location",
]


def container_tracker_query_fields() -> list[str]:
	"""Return Container Tracker fields that exist in the current site schema."""
	meta = frappe.get_meta("Container Tracker")
	return [field for field in _CONTAINER_TRACKER_FIELDS if meta.has_field(field)]


def sync_container_summary_to_project(project: str | None) -> None:
	if not project or not frappe.db.exists("Project", project):
		return
	meta = frappe.get_meta("Project")
	rows = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=[
			"eta",
			"ata",
			"bl_number",
			"custom_release_date",
			"discharging_date",
			"status",
		],
		order_by="modified desc",
	)

	updates = {}
	if rows:
		from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
			PROJECT_ATA_FIELDS,
			build_project_ata_updates,
			get_project_ata,
		)

		project_doc = frappe.get_doc("Project", project)
		existing_ata = get_project_ata(project_doc)
		atas = [r.ata for r in rows if r.ata]
		if atas and not existing_ata:
			updates.update(build_project_ata_updates(project_doc, min(atas)))

		if meta.has_field("custom_eta"):
			etas = [r.eta for r in rows if r.eta]
			if etas and not frappe.db.get_value("Project", project, "custom_eta"):
				updates["custom_eta"] = min(etas)

		if meta.has_field("custom_bl_number"):
			for r in rows:
				if r.bl_number:
					updates["custom_bl_number"] = r.bl_number
					break

		if meta.has_field("custom_custom_release_date"):
			releases = [r.custom_release_date for r in rows if r.custom_release_date]
			if releases:
				updates["custom_custom_release_date"] = max(releases)

		if meta.has_field("custom_berth_phase"):
			if (
				existing_ata
				or any(updates.get(field) for field in PROJECT_ATA_FIELDS)
				or any(r.discharging_date for r in rows)
			):
				updates["custom_berth_phase"] = "After Vessel Berthed"
			else:
				updates["custom_berth_phase"] = "Before Vessel Berth"

	if updates:
		frappe.db.set_value("Project", project, updates, update_modified=False)
	refresh_project_charge_totals(project)


def enrich_container_row(row: dict) -> dict:
	metrics = compute_container_metrics(row)
	row.update(metrics)
	return row


@frappe.whitelist()
def get_containers_for_project(project: str) -> list[dict]:
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	rows = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=container_tracker_query_fields(),
		order_by="container_number asc",
	)
	return [enrich_container_row(r) for r in rows]


_COMPUTED_METRIC_FIELDS = (
	"free_days",
	"kpa_free_days",
	"expected_empty_return",
	"port_days_used",
	"demurrage_days",
	"kpa_days",
	"days_outstanding",
	"status",
	"demurrage_daily_rate",
	"demurrage_amount",
	"kpa_port_daily_rate",
	"kpa_amount",
)


@frappe.whitelist()
def refresh_open_container_metrics() -> int:
	rows = frappe.get_all(
		"Container Tracker",
		filters={"status": ["not in", list(CLOSED_CONTAINER_STATUSES)]},
		fields=container_tracker_query_fields(),
	)
	projects = set()
	for row in rows:
		metrics = compute_container_metrics(row)
		updates = {f: metrics.get(f) for f in _COMPUTED_METRIC_FIELDS}
		frappe.db.set_value(
			"Container Tracker", row["name"], updates, update_modified=False
		)
		if row.get("project"):
			projects.add(row["project"])

	for project in projects:
		sync_container_summary_to_project(project)
		for name in frappe.get_all(
			"Container Tracker", filters={"project": project}, pluck="name"
		):
			ct = frappe.get_doc("Container Tracker", name)
			_sync_project_child_row(ct)

	return len(rows)


@frappe.whitelist()
def resync_project_container_child_rows(project: str) -> int:
	"""Push tracker status/charges back to Project Container child rows."""
	frappe.has_permission("Project", ptype="write", doc=project, throw=True)
	count = 0
	for name in frappe.get_all("Container Tracker", filters={"project": project}, pluck="name"):
		ct = frappe.get_doc("Container Tracker", name)
		apply_metrics_to_doc(ct)
		ct.save(ignore_permissions=True)
		_sync_project_child_row(ct)
		count += 1
	frappe.db.commit()
	return count
