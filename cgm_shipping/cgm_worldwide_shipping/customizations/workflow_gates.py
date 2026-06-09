"""Sea import workflow task gates - loaded from CGM Shipping Settings."""
from __future__ import annotations

import frappe

SEA_IMPORT_WORKFLOW_NAME = "CGM Sea Import Workflow"


@frappe.request_cache
def get_workflow_task_gates() -> dict[str, dict]:
	"""Map shipment workflow status → gate row from CGM Shipping Settings."""
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("custom_sea_workflow_task_gates"):
		return {}

	rows = frappe.get_single("CGM Shipping Settings").get("custom_sea_workflow_task_gates") or []
	return {
		(row.shipment_workflow_state or "").strip(): {
			"min_completed_task_seq": int(row.min_completed_task_seq or 0),
			"gate_rule": row.gate_rule or "Standard",
		}
		for row in rows
		if (row.shipment_workflow_state or "").strip()
	}


def get_gate_for_state(workflow_state: str) -> dict | None:
	return get_workflow_task_gates().get((workflow_state or "").strip())


@frappe.request_cache
def get_sea_import_workflow_states() -> list[str]:
	"""Ordered Project workflow states from CGM Sea Import Workflow metadata."""
	if not frappe.db.exists("Workflow", SEA_IMPORT_WORKFLOW_NAME):
		return []
	rows = frappe.get_all(
		"Workflow Document State",
		filters={"parent": SEA_IMPORT_WORKFLOW_NAME, "parenttype": "Workflow"},
		fields=["state"],
		order_by="idx asc",
	)
	return [row.state for row in rows if row.state]
