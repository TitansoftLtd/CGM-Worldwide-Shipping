"""Seed CGM Shipping Settings: sea import task plan and workflow document gates."""

import frappe

DEFAULT_SEA_IMPORT_TASK_ROWS = [
	{"task_subject": "Create UCR, then hand off for payment", "department": "Declaration"},
	{
		"task_subject": "Apply pre-clearance permits (DVS/NBA/VMD/ACA/KEBS as applicable)",
		"department": "Declaration",
	},
	{"task_subject": "Pay permit invoices and attach proof", "department": "Finance"},
	{"task_subject": "Receive and verify approved permits", "department": "Declaration"},
	{"task_subject": "Client inspection follow-up (if required)", "department": "Operations"},
	{"task_subject": "Obtain draft/original BL and manifest", "department": "Documentation"},
	{"task_subject": "Create customs entry and e-slip", "department": "Declaration"},
	{"task_subject": "Confirm tax payment", "department": "Finance"},
	{"task_subject": "Field verification with KRA/agencies", "department": "Field Operations"},
	{"task_subject": "Secure cargo release and gate pass", "department": "Operations"},
	{"task_subject": "Dispatch truck and monitor delivery", "department": "Transport"},
	{"task_subject": "Return empty container and upload interchange", "department": "Transport"},
]

DEFAULT_WORKFLOW_STAGE_ROWS = [
	{"shipment_workflow_state": "IDF Created", "required_stage": "Pre-IDF"},
	{"shipment_workflow_state": "Awaiting Arrival", "required_stage": "Pre-arrival"},
	{"shipment_workflow_state": "Clearing", "required_stage": "Arrival & manifest"},
	{"shipment_workflow_state": "Clearing", "required_stage": "Customs entry & taxes"},
	{"shipment_workflow_state": "Released", "required_stage": "Field clearance & release"},
	{"shipment_workflow_state": "Released", "required_stage": "Port & line (DO / charges)"},
	{"shipment_workflow_state": "Completed", "required_stage": "Transport & delivery"},
	{"shipment_workflow_state": "Completed", "required_stage": "Closure"},
]


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	changed = False

	if meta.has_field("custom_sea_import_task_template") and not settings.get("custom_sea_import_task_template"):
		for row in DEFAULT_SEA_IMPORT_TASK_ROWS:
			settings.append("custom_sea_import_task_template", row)
		changed = True

	if meta.has_field("custom_workflow_stage_requirements") and not settings.get("custom_workflow_stage_requirements"):
		for row in DEFAULT_WORKFLOW_STAGE_ROWS:
			settings.append("custom_workflow_stage_requirements", row)
		changed = True

	if changed:
		settings.save(ignore_permissions=True)
		frappe.db.commit()
