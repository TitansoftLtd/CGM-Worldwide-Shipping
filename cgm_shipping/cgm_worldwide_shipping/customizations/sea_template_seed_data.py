"""One-time seed data for sea import task template patches (not used at runtime)."""
from __future__ import annotations

DEFAULT_SEA_IMPORT_TASK_TEMPLATE: list[dict[str, str]] = [
	{"task_subject": "Receive shipment documents from Client", "department": "Operations"},
	{"task_subject": "Share documents with Declarants", "department": "Operations"},
	{"task_subject": "Create UCR (IDF)", "department": "Declaration"},
	{"task_subject": "Finance pays UCR", "department": "Finance"},
	{
		"task_subject": "Apply for Pre-Clearance Permits (DVS, NBA, VMD, ACA)",
		"department": "Declaration",
	},
	{"task_subject": "Finance pays Pre-Clearance Permits", "department": "Finance"},
	{"task_subject": "Client conducts inspection", "department": "Operations"},
	{"task_subject": "Track shipment and monitor ETA", "department": "Operations"},
	{
		"task_subject": "Receive Final Clearance Documents (B/L, Invoice, PKL, COC)",
		"department": "Documentation",
	},
	{"task_subject": "Request Manifest and Local Import Charges", "department": "Documentation"},
	{"task_subject": "Create Entry (after vessel arrival confirmation)", "department": "Declaration"},
	{"task_subject": "Finance pays Shipping Line Charges", "department": "Finance"},
	{"task_subject": "Lodge Delivery Order", "department": "Operations"},
	{"task_subject": "Confirm Entry Payment (Client/CGM)", "department": "Finance"},
	{"task_subject": "Prepare and pay Post-Clearance Permits", "department": "Declaration"},
	{"task_subject": "Field Officers conduct clearance", "department": "Field Operations"},
	{"task_subject": "Supervisor obtains KPA Invoice", "department": "Operations"},
	{"task_subject": "Finance pays KPA Invoice", "department": "Finance"},
	{"task_subject": "Book trucks and notify warehouse", "department": "Transport"},
	{"task_subject": "Load trucks and exit port", "department": "Transport"},
	{"task_subject": "Monitor delivery to destination", "department": "Transport"},
	{"task_subject": "Offload cargo", "department": "Transport"},
	{"task_subject": "Return empty container to depot", "department": "Transport"},
	{"task_subject": "Receive interchange confirmation", "department": "Transport"},
]


def seed_sea_import_task_template_to_settings() -> None:
	"""Replace CGM Shipping Settings sea task template (used by migrate patches only)."""
	import frappe

	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return
	settings = frappe.get_single("CGM Shipping Settings")
	if not settings.meta.has_field("custom_sea_import_task_template"):
		return
	settings.set("custom_sea_import_task_template", [])
	for row in DEFAULT_SEA_IMPORT_TASK_TEMPLATE:
		settings.append("custom_sea_import_task_template", row)
	settings.save(ignore_permissions=True)
