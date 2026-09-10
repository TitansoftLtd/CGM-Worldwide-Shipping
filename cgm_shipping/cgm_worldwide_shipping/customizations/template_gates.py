"""Shipment status gates: which task reaches each shipment status.

Each CGM Task Template carries its own Shipment Status Gates table. A status
counts as reached on the Project status chart once its task is Completed, and
the row order is the chart order after Draft. The tasks are this template's own
sequence numbers, so the gates are edited next to the steps they point at. They
used to live in CGM Shipping Settings and in Python tables, where renumbering a
template left them on the wrong step.
"""

from __future__ import annotations

import frappe

GATE_DOCTYPE = "CGM Task Template Gate"
GATE_RULE_STANDARD = "Standard"
# What enforce_workflow_task_gate checks for each rule (sea_clearance.py).
GATE_RULES = (
	GATE_RULE_STANDARD,
	"Permit Invoices Submitted",
	"UCR Finance Complete",
	"Entry Finance Complete",
	"KPA Finance Complete",
	"All Sea Tasks Complete",
)


def gate_map(rows) -> dict[str, dict]:
	"""State -> {min_completed_task_seq, gate_rule}, in row order."""
	out: dict[str, dict] = {}
	for row in rows:
		state = (row.get("shipment_workflow_state") or "").strip()
		if state:
			out[state] = {
				"min_completed_task_seq": int(row.get("min_completed_task_seq") or 0),
				"gate_rule": row.get("gate_rule") or GATE_RULE_STANDARD,
			}
	return out


def gate_states(rows) -> list[str]:
	"""Status chart order: Draft, then each gated status in row order."""
	return ["Draft", *gate_map(rows)]


@frappe.request_cache
def _template_gate_rows(template_name: str) -> tuple[dict, ...]:
	if not template_name or not frappe.db.table_exists(GATE_DOCTYPE):
		return ()
	return tuple(
		frappe.get_all(
			GATE_DOCTYPE,
			filters={
				"parent": template_name,
				"parenttype": "CGM Task Template",
				"parentfield": "gates",
			},
			fields=["shipment_workflow_state", "min_completed_task_seq", "gate_rule"],
			order_by="idx asc",
		)
	)


def template_has_gates(template_name: str | None) -> bool:
	return bool(_template_gate_rows(template_name or ""))


def get_template_gates(template_name: str | None) -> dict[str, dict]:
	return gate_map(_template_gate_rows(template_name or ""))


def get_template_gate_states(template_name: str | None) -> list[str]:
	return gate_states(_template_gate_rows(template_name or ""))


def task_subjects_by_sequence(task_rows) -> dict[int, str]:
	"""Sequence -> subject for a template's Tasks rows."""
	return {
		int(row.get("sequence_no") or 0): (row.get("subject") or "").strip()
		for row in task_rows
		if int(row.get("sequence_no") or 0)
	}
