"""Seed CGM Shipping Settings: sea transit task templates (when empty)."""

from __future__ import annotations

import frappe

# One-time defaults — edit anytime in CGM Shipping Settings → Sea transit task plans.
_SEA_TRANSIT_IMPORT_EXTENSION_TEMPLATE: list[dict[str, str]] = [
	{"task_subject": "Get release order from KPA", "department": "Field Operations"},
	{"task_subject": "Book trucks with KPA using release order", "department": "Transport"},
	{"task_subject": "Create delivery note", "department": "Documentation"},
	{"task_subject": "Obtain C2 and exit note", "department": "Declaration"},
	{"task_subject": "Fit ECMD and dispatch trucks", "department": "Transport"},
	{"task_subject": "Monitor to border and delivery", "department": "Transport"},
]

_SEA_TRANSIT_EXPORT_TASK_TEMPLATE: list[dict[str, str]] = [
	{"task_subject": "Receive booking and documents from client", "department": "Operations"},
	{"task_subject": "Uganda side: prepare entry and UBS permit", "department": "Operations"},
	{"task_subject": "Kenya side: prepare COC and EAC certificate", "department": "Operations"},
	{"task_subject": "Verification and release on Uganda side", "department": "Operations"},
	{"task_subject": "Goods depart Uganda toward Mombasa", "department": "Transport"},
	{"task_subject": "Goods arrive Mombasa, stuffed into vessel container", "department": "Field Operations"},
	{"task_subject": "Lodge Kenya export entry", "department": "Declaration"},
	{"task_subject": "Pay KPA and vessel sailing", "department": "Finance"},
	{"task_subject": "Receive Certificate of Export", "department": "Operations"},
]

_SEA_TRANSIT_IMPORT_SHARED_THROUGH_SEQ = 20


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	changed = False

	if meta.has_field("custom_sea_transit_import_shared_through_seq"):
		if not settings.get("custom_sea_transit_import_shared_through_seq"):
			settings.custom_sea_transit_import_shared_through_seq = (
				_SEA_TRANSIT_IMPORT_SHARED_THROUGH_SEQ
			)
			changed = True

	if meta.has_field("custom_sea_transit_import_extension_template"):
		if not settings.get("custom_sea_transit_import_extension_template"):
			for row in _SEA_TRANSIT_IMPORT_EXTENSION_TEMPLATE:
				settings.append("custom_sea_transit_import_extension_template", row)
			changed = True

	if meta.has_field("custom_sea_transit_export_task_template"):
		if not settings.get("custom_sea_transit_export_task_template"):
			for row in _SEA_TRANSIT_EXPORT_TASK_TEMPLATE:
				settings.append("custom_sea_transit_export_task_template", row)
			changed = True

	if changed:
		settings.save(ignore_permissions=True)
		frappe.db.commit()
