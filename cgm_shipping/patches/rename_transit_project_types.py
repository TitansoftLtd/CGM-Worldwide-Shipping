"""Rename transit Project Types to company naming: Transit Export / Transit Import."""

from __future__ import annotations

import frappe

_RENAMES = (
	("Transit Outbound", "Transit Export"),
	("Transit Inbound", "Transit Import"),
)


def execute():
	if not frappe.db.exists("DocType", "Project Type"):
		return

	for old_name, new_name in _RENAMES:
		_ensure_project_type(new_name)
		if frappe.db.exists("Project Type", old_name):
			if frappe.db.exists("Project Type", new_name) and old_name != new_name:
				_migrate_project_type_references(old_name, new_name)
				frappe.delete_doc("Project Type", old_name, ignore_permissions=True, force=True)
			else:
				frappe.rename_doc("Project Type", old_name, new_name, force=True, merge=False)

	_migrate_shipment_type_tracker_modes()
	frappe.db.commit()


def _ensure_project_type(name: str) -> None:
	if frappe.db.exists("Project Type", name):
		return
	frappe.get_doc({"doctype": "Project Type", "project_type": name}).insert(
		ignore_permissions=True
	)


def _migrate_project_type_references(old_name: str, new_name: str) -> None:
	if frappe.db.has_column("Project", "project_type"):
		frappe.db.sql(
			"""
			UPDATE `tabProject`
			SET project_type = %s
			WHERE project_type = %s
			""",
			(new_name, old_name),
		)
	if frappe.db.has_column("Container Tracker", "container_mode"):
		frappe.db.sql(
			"""
			UPDATE `tabContainer Tracker`
			SET container_mode = %s
			WHERE container_mode = %s
			""",
			(new_name, old_name),
		)
	if frappe.db.has_column("Shipment Type", "container_tracker_mode"):
		frappe.db.sql(
			"""
			UPDATE `tabShipment Type`
			SET container_tracker_mode = %s
			WHERE container_tracker_mode = %s
			""",
			(new_name, old_name),
		)


def _migrate_shipment_type_tracker_modes() -> None:
	if not frappe.db.has_column("Shipment Type", "container_tracker_mode"):
		return
	for old_name, new_name in _RENAMES:
		frappe.db.sql(
			"""
			UPDATE `tabShipment Type`
			SET container_tracker_mode = %s
			WHERE container_tracker_mode = %s
			""",
			(new_name, old_name),
		)
