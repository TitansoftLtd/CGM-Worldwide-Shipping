"""Sea Transit Import clearance workflow states gated by task sequence.

Mirrors Road Transit Inbound progress chart behaviour with a leaner state list
tied to ``sea_transit_import_tasks`` (15 steps). Sea import-only pills such as
UCR, permits, client inspection, and Manifest Requested are omitted.
"""

from __future__ import annotations

# Ordered Project.custom_shipment_status values for Sea Transit Import.
# Labels reuse existing Select options on Project (no new field options required).
DEFAULT_SEA_TRANSIT_IMPORT_WORKFLOW_GATES: list[dict] = [
	{"shipment_workflow_state": "Documents Received", "min_completed_task_seq": 1, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Line Paid & DO Lodged", "min_completed_task_seq": 5, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Entry Lodged", "min_completed_task_seq": 7, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Entry Paid", "min_completed_task_seq": 8, "gate_rule": "Entry Finance Complete"},
	{"shipment_workflow_state": "Field Clearance", "min_completed_task_seq": 9, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Post-clearance", "min_completed_task_seq": 10, "gate_rule": "Standard"},
	{"shipment_workflow_state": "KPA Paid", "min_completed_task_seq": 11, "gate_rule": "Standard"},
	{"shipment_workflow_state": "In Delivery", "min_completed_task_seq": 14, "gate_rule": "Standard"},
	{"shipment_workflow_state": "Completed", "min_completed_task_seq": 15, "gate_rule": "Standard"},
]

DEFAULT_SEA_TRANSIT_IMPORT_WORKFLOW_STATES: list[str] = ["Draft"] + [
	row["shipment_workflow_state"] for row in DEFAULT_SEA_TRANSIT_IMPORT_WORKFLOW_GATES
]

# Receive B/L and import documents — auto-complete when CRM CI/PKL already on the Project.
SEA_TRANSIT_IMPORT_AUTO_COMPLETE_SEQS: frozenset[int] = frozenset({1})


def get_sea_transit_import_workflow_states() -> list[str]:
	return list(DEFAULT_SEA_TRANSIT_IMPORT_WORKFLOW_STATES)


def get_sea_transit_import_workflow_gates() -> dict[str, dict]:
	"""Map state name → gate row (min_completed_task_seq)."""
	out: dict[str, dict] = {}
	for row in DEFAULT_SEA_TRANSIT_IMPORT_WORKFLOW_GATES:
		state = (row.get("shipment_workflow_state") or "").strip()
		if state:
			out[state] = {
				"min_completed_task_seq": int(row.get("min_completed_task_seq") or 0),
				"gate_rule": row.get("gate_rule") or "Standard",
			}
	return out


def get_sea_transit_import_auto_complete_sequences() -> frozenset[int]:
	return SEA_TRANSIT_IMPORT_AUTO_COMPLETE_SEQS
