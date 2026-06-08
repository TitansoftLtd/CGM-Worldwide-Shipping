"""Align CGM Shipping Settings workflow gates with sea clearance states on Project."""
from __future__ import annotations

import frappe

NEW_ROWS = [
	{"shipment_workflow_state": "UCR Applied", "required_stage": "Pre-IDF"},
	{"shipment_workflow_state": "Entry Lodged", "required_stage": "Arrival & manifest"},
	{"shipment_workflow_state": "Entry Paid", "required_stage": "Customs entry & taxes"},
	{"shipment_workflow_state": "Field Clearance", "required_stage": "Field clearance & release"},
	{"shipment_workflow_state": "In Delivery", "required_stage": "Port & line (DO / charges)"},
	{"shipment_workflow_state": "Completed", "required_stage": "Transport & delivery"},
	{"shipment_workflow_state": "Completed", "required_stage": "Closure"},
]

LEGACY_STATES = (
	"IDF Created",
	"Awaiting Arrival",
	"Clearing",
	"Released",
)


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return
	settings = frappe.get_doc("CGM Shipping Settings")
	if not settings.meta.has_field("custom_workflow_stage_requirements"):
		return
	rows = settings.get("custom_workflow_stage_requirements") or []
	kept = [r for r in rows if r.shipment_workflow_state not in LEGACY_STATES]
	existing_states = {r.shipment_workflow_state for r in kept}
	for row in NEW_ROWS:
		if row["shipment_workflow_state"] in existing_states:
			continue
		kept.append(row)
		existing_states.add(row["shipment_workflow_state"])
	settings.set("custom_workflow_stage_requirements", [])
	for row in kept:
		settings.append("custom_workflow_stage_requirements", row)
	settings.save(ignore_permissions=True)
	frappe.db.commit()
