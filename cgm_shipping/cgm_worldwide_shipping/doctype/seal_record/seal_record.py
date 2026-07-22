# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document


class SealRecord(Document):
	pass


def ensure_seal_record_for_container(
	project: str,
	seal_number: str,
	container_tracker: str | None = None,
	*,
	new_seal_number: str | None = None,
	reason_for_new_seal_number: str | None = None,
) -> str | None:
	"""Create or update Seal Record for a project/container seal from BL or tracker."""
	project = (project or "").strip()
	seal_number = (seal_number or "").strip()
	if not project or not seal_number:
		return None
	if not frappe.db.exists("DocType", "Seal Record"):
		return None

	tracker = (container_tracker or "").strip() or None
	new_seal = (new_seal_number or "").strip() if new_seal_number is not None else None
	reason = (
		(reason_for_new_seal_number or "").strip()
		if reason_for_new_seal_number is not None
		else None
	)

	existing = frappe.db.exists("Seal Record", seal_number)
	if existing:
		updates: dict = {}
		row = frappe.db.get_value(
			"Seal Record",
			existing,
			["project", "container_tracker", "new_seal_number", "reason_for_new_seal_number"],
			as_dict=True,
		)
		if row:
			if project and row.project != project:
				updates["project"] = project
			if tracker and row.container_tracker != tracker:
				updates["container_tracker"] = tracker
			if new_seal is not None and (row.new_seal_number or "") != new_seal:
				updates["new_seal_number"] = new_seal
			if reason is not None and (row.reason_for_new_seal_number or "") != reason:
				updates["reason_for_new_seal_number"] = reason
		if updates:
			frappe.db.set_value("Seal Record", existing, updates, update_modified=True)
		return existing

	doc = frappe.get_doc(
		{
			"doctype": "Seal Record",
			"project": project,
			"seal_number": seal_number,
			"container_tracker": tracker,
			"new_seal_number": new_seal or "",
			"reason_for_new_seal_number": reason or "",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def sync_seal_record_from_tracker(tracker) -> str | None:
	"""Mirror Container Tracker seal fields onto the matching Seal Record."""
	if not tracker:
		return None
	project = (tracker.get("project") if hasattr(tracker, "get") else None) or ""
	seal_number = (tracker.get("seal_no") if hasattr(tracker, "get") else None) or ""
	tracker_name = tracker.name if hasattr(tracker, "name") else tracker.get("name")
	if not project or not seal_number:
		# Fall back: find Seal Record already linked to this tracker
		if tracker_name:
			linked = frappe.db.get_value(
				"Seal Record",
				{"container_tracker": tracker_name},
				["name", "seal_number"],
				as_dict=True,
			)
			if linked:
				seal_number = linked.seal_number
				project = project or frappe.db.get_value("Seal Record", linked.name, "project")
		if not project or not seal_number:
			return None

	return ensure_seal_record_for_container(
		project,
		seal_number,
		tracker_name,
		new_seal_number=tracker.get("new_seal_number") or "",
		reason_for_new_seal_number=tracker.get("reason_for_new_seal_number") or "",
	)


def sync_seal_records_from_bill_of_lading(bl) -> list[str]:
	"""Upsert Seal Records for BL container rows when a Project links this BL."""
	bl_name = bl.name if hasattr(bl, "name") else bl
	if not bl_name:
		return []

	projects = frappe.get_all(
		"Project",
		filters={"custom_bill_of_lading": bl_name},
		pluck="name",
	)
	if not projects:
		return []

	from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
		find_tracker_by_identity,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
		container_row_cargo_size,
	)

	bl_doc = bl if hasattr(bl, "get") else frappe.get_doc("Bill of Lading", bl_name)
	created: list[str] = []
	for row in bl_doc.get("container_information") or []:
		seal_no = (row.get("seal_no") or "").strip()
		container_number = (row.get("container_number") or "").strip()
		if not seal_no or not container_number:
			continue

		for project in projects:
			tracker = (row.get("container_tracker") or "").strip()
			if not tracker:
				tracker = find_tracker_by_identity(
					project, container_number, container_row_cargo_size(row)
				) or ""
			name = ensure_seal_record_for_container(project, seal_no, tracker or None)
			if name:
				created.append(name)
	return created
