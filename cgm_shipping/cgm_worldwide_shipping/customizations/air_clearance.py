"""Air Import / Air Export clearance workflow states gated by task sequence.

Mirrors Sea Import progress-chart behaviour with states tied to
``air_import_tasks`` (16 steps) and ``air_export_tasks`` (11 steps).
Labels reuse existing Project.custom_shipment_status Select options.
"""

from __future__ import annotations

# Air Import: proforma → UCR → permits → AWB/arrival → entry → release.
DEFAULT_AIR_IMPORT_WORKFLOW_GATES: list[dict] = [
	{"shipment_workflow_state": "Documents Received", "min_completed_task_seq": 1},
	{"shipment_workflow_state": "UCR Applied", "min_completed_task_seq": 2},
	{"shipment_workflow_state": "UCR Paid", "min_completed_task_seq": 3},
	{"shipment_workflow_state": "Pre-clearance", "min_completed_task_seq": 5},
	{"shipment_workflow_state": "Client Inspection", "min_completed_task_seq": 7},
	{"shipment_workflow_state": "Final Docs Received", "min_completed_task_seq": 8},
	{"shipment_workflow_state": "Manifest Requested", "min_completed_task_seq": 9},
	{"shipment_workflow_state": "Entry Lodged", "min_completed_task_seq": 10},
	{"shipment_workflow_state": "Entry Paid", "min_completed_task_seq": 12},
	{"shipment_workflow_state": "Post-clearance", "min_completed_task_seq": 13},
	{"shipment_workflow_state": "Field Clearance", "min_completed_task_seq": 15},
	{"shipment_workflow_state": "Completed", "min_completed_task_seq": 16},
]

DEFAULT_AIR_IMPORT_WORKFLOW_STATES: list[str] = ["Draft"] + [
	row["shipment_workflow_state"] for row in DEFAULT_AIR_IMPORT_WORKFLOW_GATES
]

# Air Export: client docs → AWB → export entry → airport → flight → COE.
DEFAULT_AIR_EXPORT_WORKFLOW_GATES: list[dict] = [
	{"shipment_workflow_state": "Documents Received", "min_completed_task_seq": 1},
	{"shipment_workflow_state": "Final Docs Received", "min_completed_task_seq": 4},
	{"shipment_workflow_state": "Entry Lodged", "min_completed_task_seq": 5},
	{"shipment_workflow_state": "Entry Paid", "min_completed_task_seq": 8},
	{"shipment_workflow_state": "In Transit", "min_completed_task_seq": 10},
	{"shipment_workflow_state": "Completed", "min_completed_task_seq": 11},
]

DEFAULT_AIR_EXPORT_WORKFLOW_STATES: list[str] = ["Draft"] + [
	row["shipment_workflow_state"] for row in DEFAULT_AIR_EXPORT_WORKFLOW_GATES
]


def _gates_map(rows: list[dict]) -> dict[str, dict]:
	out: dict[str, dict] = {}
	for row in rows:
		state = (row.get("shipment_workflow_state") or "").strip()
		if state:
			out[state] = {
				"min_completed_task_seq": int(row.get("min_completed_task_seq") or 0),
				"gate_rule": "Standard",
			}
	return out


def get_air_import_workflow_states() -> list[str]:
	return list(DEFAULT_AIR_IMPORT_WORKFLOW_STATES)


def get_air_import_workflow_gates() -> dict[str, dict]:
	return _gates_map(DEFAULT_AIR_IMPORT_WORKFLOW_GATES)


def get_air_export_workflow_states() -> list[str]:
	return list(DEFAULT_AIR_EXPORT_WORKFLOW_STATES)


def get_air_export_workflow_gates() -> dict[str, dict]:
	return _gates_map(DEFAULT_AIR_EXPORT_WORKFLOW_GATES)
