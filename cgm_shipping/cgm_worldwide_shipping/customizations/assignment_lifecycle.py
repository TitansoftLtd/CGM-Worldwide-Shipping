"""Assignments follow the work: closed when it finishes, reopened when it comes back.

A ToDo is how CGM records who is responsible for something. Three notification
rules read that record to decide who to tell, so a stale assignment is not an
untidy list - it sends the wrong person a message and stops the right people
getting one.

What already existed, and what did not:

* **Task completion** closes its assignments. Twice over, in fact: ERPNext's
  `Task.unassign_todo()` and CGM's own `CGMTask` both call
  `close_all_assignments`. That half works.
* **Task reopening** did nothing. A task sent back to Open kept its assignments
  Closed, so the person who owns the work again looks unassigned.
* **Project completion** did nothing either. Neither ERPNext nor CGM closes a
  Project's assignments, so a finished shipment keeps its assignees for good.
  Nothing has surfaced yet only because no shipment on this site has reached a
  finished status.

Both directions are handled here, for Task and Project, so the two cannot drift
apart again.

Only `Closed` assignments are reopened. `Cancelled` means somebody deliberately
removed that person, and reviving them would undo a decision rather than restore a
state.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	COMPLETED_SHIPMENT_STATUSES,
)

#: Task statuses that mean the work is over.
TASK_FINISHED_STATUSES = frozenset({"Completed", "Cancelled"})


def close_assignments(doctype: str, name: str) -> int:
	"""Close every open assignment on a document. Returns how many moved."""
	from frappe.desk.form.assign_to import set_status

	rows = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": doctype,
			"reference_name": name,
			"status": ["not in", ["Cancelled", "Closed"]],
		},
		fields=["name", "allocated_to"],
	)
	for row in rows:
		set_status(
			doctype,
			name,
			todo=row.name,
			assign_to=row.allocated_to,
			status="Closed",
			ignore_permissions=True,
		)
	return len(rows)


def reopen_assignments(doctype: str, name: str) -> int:
	"""Put closed assignments back to Open. Returns how many moved.

	Cancelled rows are left alone: that status records a person being taken off
	the job, which reopening the work does not undo.
	"""
	from frappe.desk.form.assign_to import set_status

	rows = frappe.get_all(
		"ToDo",
		filters={"reference_type": doctype, "reference_name": name, "status": "Closed"},
		fields=["name", "allocated_to"],
	)
	for row in rows:
		set_status(
			doctype,
			name,
			todo=row.name,
			assign_to=row.allocated_to,
			status="Open",
			ignore_permissions=True,
		)
	return len(rows)


def _previous(doc, fieldname: str):
	"""The value this field held before the current save, or None on insert."""
	if doc.is_new():
		return None
	before = doc.get_doc_before_save()
	return before.get(fieldname) if before else None


def on_task_update(doc, method=None) -> None:
	"""Reopen a task's assignments when it comes back from finished.

	Closing is left to ERPNext and `CGMTask`, which already do it on the way in.
	Doing it again here would be harmless but would hide where it happens.
	"""
	previous = _previous(doc, "status")
	if previous is None or previous == doc.status:
		return
	if previous in TASK_FINISHED_STATUSES and doc.status not in TASK_FINISHED_STATUSES:
		reopen_assignments(doc.doctype, doc.name)


def on_project_update(doc, method=None) -> None:
	"""Close a shipment's assignments when it finishes, reopen them if it returns.

	Keyed on `custom_shipment_status` rather than ERPNext's `status`, because that
	is the field CGM actually moves through the shipment lifecycle; every project
	on this site sits at ERPNext status Open regardless of how far along it is.
	"""
	field = "custom_shipment_status"
	if not doc.meta.has_field(field):
		return
	previous = _previous(doc, field)
	if previous is None:
		return
	current = doc.get(field)
	if previous == current:
		return

	was_finished = previous in COMPLETED_SHIPMENT_STATUSES
	is_finished = current in COMPLETED_SHIPMENT_STATUSES
	if is_finished and not was_finished:
		close_assignments(doc.doctype, doc.name)
	elif was_finished and not is_finished:
		reopen_assignments(doc.doctype, doc.name)
