# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_charges import (
	apply_metrics_to_doc,
	compute_container_metrics,
)


class ContainerTracker(Document):
	def validate(self):
		self._apply_bill_of_lading_defaults()
		apply_metrics_to_doc(self)

	def _apply_bill_of_lading_defaults(self):
		bl = self.get("custom_bill_of_lading")
		if bl:
			self.bl_number = bl
		if self.get("custom_bl_container_select") and not self.container_number:
			self.container_number = self.custom_bl_container_select

	def on_update(self):
		sync_container_summary_to_project(self.project)


_CONTAINER_TRACKER_FIELDS = [
	"name",
	"project",
	"container_number",
	"batch_bl_no",
	"bl_number",
	"container_mode",
	"delivery_location",
	"eta",
	"ata",
	"discharging_date",
	"icd_mombasa_discharge_date",
	"custom_release_date",
	"gate_out_date_port",
	"delivery_date",
	"actual_empty_return",
	"expected_empty_return",
	"gate_in_date_depot",
	"icd_gate_in_date",
	"icd_gate_out_date",
	"free_days",
	"port_days_used",
	"daily_demurrage_rate",
	"daily_detention_rate",
	"demurrage_days",
	"detention_days",
	"demurrage_amount",
	"detention_amount",
	"demurrage_date",
	"days_outstanding",
	"status",
]


def sync_container_summary_to_project(project: str | None) -> None:
	"""Roll up first/latest container dates onto Project header."""
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
			"batch_bl_no",
			"custom_release_date",
			"discharging_date",
			"status",
		],
		order_by="modified desc",
	)
	if not rows:
		return

	updates = {}
	# Don't clobber a manually-set Project ATA; only fill when empty (mirrors custom_eta below).
	existing_ata = (
		frappe.db.get_value("Project", project, "custom_ata")
		if meta.has_field("custom_ata")
		else None
	)
	if meta.has_field("custom_ata"):
		atas = [r.ata for r in rows if r.ata]
		if atas and not existing_ata:
			updates["custom_ata"] = min(atas)

	if meta.has_field("custom_eta"):
		etas = [r.eta for r in rows if r.eta]
		if etas and not frappe.db.get_value("Project", project, "custom_eta"):
			updates["custom_eta"] = min(etas)

	if meta.has_field("custom_bl_number"):
		for r in rows:
			if r.bl_number:
				updates["custom_bl_number"] = r.bl_number
				break

	if meta.has_field("custom_batch_no"):
		for r in rows:
			if r.batch_bl_no:
				updates["custom_batch_no"] = r.batch_bl_no
				break

	if meta.has_field("custom_custom_release_date"):
		releases = [r.custom_release_date for r in rows if r.custom_release_date]
		if releases:
			updates["custom_custom_release_date"] = max(releases)

	if meta.has_field("custom_berth_phase"):
		if existing_ata or updates.get("custom_ata") or any(r.discharging_date for r in rows):
			updates["custom_berth_phase"] = "After Vessel Berthed"
		else:
			updates["custom_berth_phase"] = "Before Vessel Berth"

	if updates:
		frappe.db.set_value("Project", project, updates, update_modified=False)


def enrich_container_row(row: dict) -> dict:
	"""Merge stored DB values with live computed metrics (for dashboards/reports)."""
	metrics = compute_container_metrics(row)
	row.update(metrics)
	return row


@frappe.whitelist()
def get_containers_for_project(project: str) -> list[dict]:
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	rows = frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=_CONTAINER_TRACKER_FIELDS,
		order_by="container_number asc",
	)
	return [enrich_container_row(r) for r in rows]


@frappe.whitelist()
def refresh_open_container_metrics() -> int:
	"""Daily job: recompute outstanding/detention for containers not yet returned."""
	names = frappe.get_all(
		"Container Tracker",
		filters={"actual_empty_return": ["is", "not set"]},
		pluck="name",
	)
	projects = set()
	for name in names:
		doc = frappe.get_doc("Container Tracker", name)
		apply_metrics_to_doc(doc)
		doc.db_update()
		if doc.project:
			projects.add(doc.project)

	for project in projects:
		sync_container_summary_to_project(project)

	return len(names)
