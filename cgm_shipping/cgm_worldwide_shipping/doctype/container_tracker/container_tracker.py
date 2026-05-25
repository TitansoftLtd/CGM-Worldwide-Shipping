# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, getdate, today


class ContainerTracker(Document):
	def validate(self):
		self._calc_expected_empty_return()
		self._calc_demurrage_detention()
		self._update_status()

	def on_update(self):
		sync_container_summary_to_project(self.project)

	def _calc_expected_empty_return(self):
		if self.gate_out_date_port and self.free_days:
			self.expected_empty_return = add_days(self.gate_out_date_port, self.free_days)

	def _calc_demurrage_detention(self):
		self.port_days_used = 0
		self.demurrage_days = 0
		self.detention_days = 0
		self.demurrage_amount = 0
		self.demurrage_date = None
		self.days_outstanding = 0

		discharge = self.discharging_date or self.icd_mombasa_discharge_date
		if discharge and self.gate_out_date_port:
			self.port_days_used = date_diff(self.gate_out_date_port, discharge)
			agreed = self.free_days or 0
			self.demurrage_days = max(0, self.port_days_used - agreed)
			if self.demurrage_days and agreed:
				self.demurrage_date = add_days(discharge, agreed)
			elif self.demurrage_days:
				self.demurrage_date = add_days(discharge, 1)

		if self.gate_out_date_port and self.actual_empty_return:
			self.detention_days = max(0, date_diff(self.actual_empty_return, self.gate_out_date_port))

		rate = self.daily_demurrage_rate or 0
		self.demurrage_amount = self.demurrage_days * rate

		if self.expected_empty_return and not self.actual_empty_return:
			self.days_outstanding = max(0, date_diff(today(), self.expected_empty_return))

	def _update_status(self):
		if self.actual_empty_return:
			self.status = "Empty Returned"
			return
		if self.expected_empty_return and not self.actual_empty_return:
			if getdate(today()) > getdate(self.expected_empty_return):
				self.status = "Overdue"
				return
		if self.delivery_date and not self.actual_empty_return:
			self.status = "Empty Pending"
		elif self.gate_out_date_port:
			self.status = "Dispatched"
		elif self.discharging_date or self.custom_release_date:
			self.status = "Delivered"


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
	if meta.has_field("custom_ata"):
		atas = [r.ata for r in rows if r.ata]
		if atas:
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
		if updates.get("custom_ata") or any(r.discharging_date for r in rows):
			updates["custom_berth_phase"] = "After Vessel Berthed"
		else:
			updates["custom_berth_phase"] = "Before Vessel Berth"

	if updates:
		frappe.db.set_value("Project", project, updates, update_modified=False)


@frappe.whitelist()
def get_containers_for_project(project: str) -> list[dict]:
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	return frappe.get_all(
		"Container Tracker",
		filters={"project": project},
		fields=[
			"name",
			"container_number",
			"batch_bl_no",
			"bl_number",
			"container_mode",
			"eta",
			"ata",
			"discharging_date",
			"gate_out_date_port",
			"delivery_date",
			"actual_empty_return",
			"expected_empty_return",
			"free_days",
			"demurrage_days",
			"detention_days",
			"days_outstanding",
			"status",
		],
		order_by="container_number asc",
	)
