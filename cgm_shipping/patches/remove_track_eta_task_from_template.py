"""Remove legacy Track shipment and monitor ETA row from sea import task template (new projects only)."""

from __future__ import annotations

import frappe

TRACK_ETA_SUBJECT = "Track shipment and monitor ETA"


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("custom_sea_import_task_template"):
		return

	rows = list(settings.get("custom_sea_import_task_template") or [])
	if not any((row.task_subject or "").strip() == TRACK_ETA_SUBJECT for row in rows):
		return

	new_rows = [
		{"task_subject": row.task_subject, "department": row.department}
		for row in rows
		if (row.task_subject or "").strip() != TRACK_ETA_SUBJECT
	]
	settings.set("custom_sea_import_task_template", [])
	for row in new_rows:
		settings.append("custom_sea_import_task_template", row)
	settings.save(ignore_permissions=True)
	frappe.db.commit()
