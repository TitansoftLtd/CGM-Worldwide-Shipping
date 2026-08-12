"""Road Transit Inbound clearance workflow states gated by task sequence.

Mirrors Sea Import progress chart behaviour with a leaner state list tied to
``road_transit_inbound_tasks`` (13 steps).
"""

from __future__ import annotations

# Ordered Project.custom_shipment_status values for Road Transit Inbound.
# Labels reuse existing Select options on Project (no new field options required).
DEFAULT_ROAD_TRANSIT_INBOUND_WORKFLOW_GATES: list[dict] = [
	{"shipment_workflow_state": "Documents Received", "min_completed_task_seq": 1},
	{"shipment_workflow_state": "UCR Applied", "min_completed_task_seq": 2},
	{"shipment_workflow_state": "UCR Paid", "min_completed_task_seq": 3},
	{"shipment_workflow_state": "Pre-clearance", "min_completed_task_seq": 5},
	{"shipment_workflow_state": "Entry Lodged", "min_completed_task_seq": 6},
	{"shipment_workflow_state": "Entry Paid", "min_completed_task_seq": 7},
	{"shipment_workflow_state": "Post-clearance", "min_completed_task_seq": 9},
	{"shipment_workflow_state": "Field Clearance", "min_completed_task_seq": 10},
	{"shipment_workflow_state": "In Delivery", "min_completed_task_seq": 12},
	{"shipment_workflow_state": "Completed", "min_completed_task_seq": 13},
]

DEFAULT_ROAD_TRANSIT_INBOUND_WORKFLOW_STATES: list[str] = ["Draft"] + [
	row["shipment_workflow_state"] for row in DEFAULT_ROAD_TRANSIT_INBOUND_WORKFLOW_GATES
]

# Receive shipment documents — auto-complete when CRM CI/PKL already on the Project.
ROAD_TRANSIT_INBOUND_AUTO_COMPLETE_SEQS: frozenset[int] = frozenset({1})


def get_road_transit_inbound_workflow_states() -> list[str]:
	return list(DEFAULT_ROAD_TRANSIT_INBOUND_WORKFLOW_STATES)


def get_road_transit_inbound_workflow_gates() -> dict[str, dict]:
	"""Map state name → gate row (min_completed_task_seq)."""
	out: dict[str, dict] = {}
	for row in DEFAULT_ROAD_TRANSIT_INBOUND_WORKFLOW_GATES:
		state = (row.get("shipment_workflow_state") or "").strip()
		if state:
			out[state] = {
				"min_completed_task_seq": int(row.get("min_completed_task_seq") or 0),
				"gate_rule": "Standard",
			}
	return out


def get_road_transit_inbound_auto_complete_sequences() -> frozenset[int]:
	return ROAD_TRANSIT_INBOUND_AUTO_COMPLETE_SEQS
