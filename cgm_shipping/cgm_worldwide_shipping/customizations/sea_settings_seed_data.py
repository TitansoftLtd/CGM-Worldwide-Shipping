"""Default CGM Sea Import status gates and workflow states used by seeds and migrate patches."""

from __future__ import annotations

DEFAULT_SEA_WORKFLOW_TASK_GATES: list[dict] = [
	{"shipment_workflow_state": "Documents Received", "min_completed_task_seq": 1, "gate_rule": "Standard"},
	{"shipment_workflow_state": "UCR Applied", "min_completed_task_seq": 3, "gate_rule": "Standard"},
	{"shipment_workflow_state": "UCR Paid", "min_completed_task_seq": 4, "gate_rule": "UCR Finance Complete"},
	{"shipment_workflow_state": "Pre-clearance", "min_completed_task_seq": 5, "gate_rule": "Permit Invoices Submitted"},
	{"shipment_workflow_state": "In Transit", "min_completed_task_seq": 8, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Final Docs Received", "min_completed_task_seq": 8, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Line Paid & DO Lodged", "min_completed_task_seq": 14, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Entry Lodged", "min_completed_task_seq": 12, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Entry Paid", "min_completed_task_seq": 13, "gate_rule": "Entry Finance Complete"},
	{"shipment_workflow_state": "Post-clearance", "min_completed_task_seq": 15, "gate_rule": "Permit Invoices Submitted"},
	{"shipment_workflow_state": "Field Clearance", "min_completed_task_seq": 17, "gate_rule": "Standard"},
	{"shipment_workflow_state": "KPA Paid", "min_completed_task_seq": 19, "gate_rule": "KPA Finance Complete"},
	{"shipment_workflow_state": "In Delivery", "min_completed_task_seq": 21, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Containers Returned", "min_completed_task_seq": 24, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Completed", "min_completed_task_seq": 25, "gate_rule": "All Sea Tasks Complete"},
]

# CGM Sea Import Workflow states, in chart order. Client Inspection has no gate -
# no task reaches it - but stays a status the shipment can be moved to by hand.
DEFAULT_SEA_IMPORT_WORKFLOW_STATES: list[str] = [
	"Draft",
	"Documents Received",
	"UCR Applied",
	"UCR Paid",
	"Pre-clearance",
	"Client Inspection",
	"In Transit",
	"Final Docs Received",
	"Line Paid & DO Lodged",
	"Entry Lodged",
	"Entry Paid",
	"Post-clearance",
	"Field Clearance",
	"KPA Paid",
	"CFS Paid",
	"In Delivery",
	"Containers Returned",
	"Completed",
]
