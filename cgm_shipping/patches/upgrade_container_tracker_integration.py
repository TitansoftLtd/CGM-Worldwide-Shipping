"""Upgrade container tracker ↔ task integration (transport independence, delivery location)."""

from __future__ import annotations

import frappe


def execute():
	_migrate_delivery_location_to_clearance_station()
	_remove_transport_task_depends_on()
	_ensure_delivery_note_document_type()
	_ensure_field_officer_fields()


def _migrate_delivery_location_to_clearance_station() -> None:
	if not frappe.db.exists("DocType", "Container Tracker"):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, delivery_location
		FROM `tabContainer Tracker`
		WHERE IFNULL(delivery_location, '') != ''
		""",
		as_dict=True,
	)
	for row in rows:
		value = (row.delivery_location or "").strip()
		if not value or frappe.db.exists("Clearance Station", value):
			continue
		match = frappe.db.get_value(
			"Clearance Station",
			{"cfs_name": value},
			"name",
		)
		if match:
			frappe.db.set_value(
				"Container Tracker",
				row.name,
				"delivery_location",
				match,
				update_modified=False,
			)


def _remove_transport_task_depends_on() -> None:
	"""Drop sequential depends_on links between transport tasks 20–24."""
	transport_tasks = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": "SEA_IMPORT_E2E",
			"custom_sequence_no": ["between", [20, 24]],
		},
		fields=["name"],
	)
	transport_names = {t.name for t in transport_tasks}
	if not transport_names:
		return

	for task_name in transport_names:
		depends_rows = frappe.get_all(
			"Task Depends On",
			filters={"parent": task_name},
			fields=["name", "task"],
		)
		for dep in depends_rows:
			if dep.task in transport_names:
				frappe.delete_doc(
					"Task Depends On",
					dep.name,
					ignore_permissions=True,
					force=True,
				)


def _ensure_delivery_note_document_type() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		ensure_task_document_types,
	)

	ensure_task_document_types()


def _ensure_field_officer_fields() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
		ensure_field_officer_task_fields,
	)

	ensure_field_officer_task_fields()
