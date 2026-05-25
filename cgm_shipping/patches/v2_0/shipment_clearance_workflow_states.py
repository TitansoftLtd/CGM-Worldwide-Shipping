"""Ensure Workflow State / Action Master records exist for Shipment Clearance Workflow."""
from __future__ import annotations

import frappe

WORKFLOW_STATES = {
	"Draft": "Primary",
	"Documents Received": "Warning",
	"IDF Open": "Primary",
	"Pre-clearance": "Primary",
	"In Transit": "Info",
	"Entry Lodged": "Warning",
	"Taxes Paid": "Success",
	"Clearance": "Warning",
	"Released": "Primary",
	"Settled": "Success",
}

WORKFLOW_ACTIONS = (
	"Receive Documents",
	"Open IDF",
	"Start Pre-clearance",
	"Mark In Transit",
	"Lodge Entry",
	"Confirm Taxes Paid",
	"Start Clearance",
	"Release Cargo",
	"Settle",
)


def execute():
	for state, style in WORKFLOW_STATES.items():
		_ensure_workflow_state(state, style)
	for action in WORKFLOW_ACTIONS:
		_ensure_workflow_action(action)
	frappe.db.commit()


def _ensure_workflow_state(name: str, style: str) -> None:
	if frappe.db.exists("Workflow State", name):
		return
	doc = frappe.new_doc("Workflow State")
	doc.workflow_state_name = name
	doc.style = style
	doc.insert(ignore_permissions=True)


def _ensure_workflow_action(name: str) -> None:
	if frappe.db.exists("Workflow Action Master", name):
		return
	doc = frappe.new_doc("Workflow Action Master")
	doc.workflow_action_name = name
	doc.insert(ignore_permissions=True)
