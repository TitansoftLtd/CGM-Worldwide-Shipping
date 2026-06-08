"""Backfill CGM Shipping Settings: sea import task plan and workflow document gates.

Self-contained: previously delegated to the removed seed patch. Fills the settings
tables once on sites where they are still empty.
"""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_template_seed_data import (
	DEFAULT_SEA_IMPORT_TASK_TEMPLATE,
)

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
	"""Sites where workflow gates were added after sea task seed: fill the tables once."""
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	changed = False

	if meta.has_field("custom_sea_import_task_template") and not settings.get(
		"custom_sea_import_task_template"
	):
		for row in DEFAULT_SEA_IMPORT_TASK_TEMPLATE:
			settings.append("custom_sea_import_task_template", row)
		changed = True

	if meta.has_field("custom_workflow_stage_requirements") and not settings.get(
		"custom_workflow_stage_requirements"
	):
		for row in DEFAULT_WORKFLOW_STAGE_ROWS:
			settings.append("custom_workflow_stage_requirements", row)
		changed = True

	if changed:
		settings.save(ignore_permissions=True)
		frappe.db.commit()
