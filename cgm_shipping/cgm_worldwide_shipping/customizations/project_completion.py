"""When a shipment finished.

`custom_shipment_status` says whether a shipment is finished, but not when it finished,
so "which shipments completed in September" could not be asked. This records the day the
work ended on the Project itself, as a date that can be filtered and reported on.

The date recorded is the day the shipment's last task was completed, not the day the
status happened to be written. Those differ whenever a status is corrected later, and the
useful answer is when the work ended.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	COMPLETED_SHIPMENT_STATUSES,
)

COMPLETION_DATE_FIELD = "custom_completion_date"
SHIPMENT_STATUS_FIELD = "custom_shipment_status"


def set_completion_date_on_update(doc, method=None) -> None:
	"""Stamp or clear the Project's completion date as its shipment status changes.

	Runs on `on_update`, alongside the assignment lifecycle, which watches the same
	status crossing. Written with `db_set` so stamping a date does not start another
	round of save hooks, and so the document in hand matches the row.
	"""
	if not doc.meta.has_field(COMPLETION_DATE_FIELD):
		return

	wanted = _wanted_date(doc.name, doc.get(SHIPMENT_STATUS_FIELD), doc.get(COMPLETION_DATE_FIELD))
	if wanted is not _UNCHANGED:
		doc.db_set(COMPLETION_DATE_FIELD, wanted, update_modified=False)


def sync_completion_date(project: str, status: str | None) -> None:
	"""The same reconciliation for a status written straight to the row.

	`sea_clearance.sync_project_shipment_status_from_tasks` advances the shipment status
	with `frappe.db.set_value` when tasks complete, which runs no document hooks. That is
	the path that finishes most shipments, so without this the date would only ever be
	stamped when somebody happened to save the Project by hand afterwards.
	"""
	if not frappe.get_meta("Project").has_field(COMPLETION_DATE_FIELD):
		return

	recorded = frappe.db.get_value("Project", project, COMPLETION_DATE_FIELD)
	wanted = _wanted_date(project, status, recorded)
	if wanted is not _UNCHANGED:
		frappe.db.set_value(
			"Project", project, COMPLETION_DATE_FIELD, wanted, update_modified=False
		)


#: Distinguishes "leave it alone" from "clear it", since clearing writes None.
_UNCHANGED = object()


def _wanted_date(project: str, status: str | None, recorded):
	"""The date the row should hold, or `_UNCHANGED` when it already holds it."""
	finished = (status or "") in COMPLETED_SHIPMENT_STATUSES

	if finished and not recorded:
		return last_task_completion_date(project)

	if not finished and recorded:
		# Reopened. Clearing it keeps the field honest and lets the next completion
		# stamp the date it actually finished on.
		return None

	return _UNCHANGED


def last_task_completion_date(project: str) -> str:
	"""The day the project's last task was completed, or today if none says.

	A task completed with no date, and a project whose status was set by hand without
	tasks, both fall back to today: an approximate date still answers "which shipments
	finished last month", where no date at all leaves the shipment out of every report.
	"""
	latest = frappe.db.sql(
		"""
		SELECT MAX(completed_on)
		FROM `tabTask`
		WHERE project = %s AND status = 'Completed' AND completed_on IS NOT NULL
		""",
		project,
	)
	value = latest[0][0] if latest and latest[0] else None
	return str(getdate(value) if value else nowdate())
