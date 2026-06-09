"""One-time seed data for sea workflow task gate patches (not used at runtime)."""
from __future__ import annotations

DEFAULT_SEA_WORKFLOW_TASK_GATES: list[dict] = [
	{"shipment_workflow_state": "Documents Received", "min_completed_task_seq": 1, "gate_rule": "Standard"},
	{"shipment_workflow_state": "UCR Applied", "min_completed_task_seq": 3, "gate_rule": "Standard"},
	{"shipment_workflow_state": "UCR Paid", "min_completed_task_seq": 4, "gate_rule": "UCR Finance Complete"},
	{"shipment_workflow_state": "Pre-clearance", "min_completed_task_seq": 5, "gate_rule": "Permit Invoices Submitted"},
	{"shipment_workflow_state": "Client Inspection", "min_completed_task_seq": 7, "gate_rule": "Standard"},
	{"shipment_workflow_state": "In Transit", "min_completed_task_seq": 8, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Final Docs Received", "min_completed_task_seq": 9, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Manifest Requested", "min_completed_task_seq": 10, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Entry Lodged", "min_completed_task_seq": 11, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Line Paid & DO Lodged", "min_completed_task_seq": 13, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Entry Paid", "min_completed_task_seq": 14, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Post-clearance", "min_completed_task_seq": 15, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Field Clearance", "min_completed_task_seq": 16, "gate_rule": "Standard"},
	{"shipment_workflow_state": "KPA Paid", "min_completed_task_seq": 18, "gate_rule": "Standard"},
	{"shipment_workflow_state": "In Delivery", "min_completed_task_seq": 18, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Containers Returned", "min_completed_task_seq": 23, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Completed", "min_completed_task_seq": 24, "gate_rule": "All Sea Tasks Complete"},
]
