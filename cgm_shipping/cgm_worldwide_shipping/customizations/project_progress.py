"""Keep a Project's percentage honest about its tasks.

ERPNext recomputes `percent_complete` inside `Project.validate` and from
`Task.update_project`, so it is only correct while every task write goes through the
ORM. Several patches reopen tasks with `frappe.db.set_value`, which writes the row and
runs no hooks, so the project is never told to recount. PROJ-0002 was left reading 100%
with a task still open, and because ERPNext sets the status from the percentage it also
read Completed, which put a live shipment into everyone's "Completed" filter.

This reconciles the two. It runs from `after_migrate` rather than as a patch because a
patch runs once and the next patch to reopen a task would put the drift straight back.

Only `Task Completion` projects are touched. `Manual` is somebody's own figure, and the
progress and weight methods compute from fields this does not read.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

#: ERPNext counts a cancelled task as accounted for, not outstanding.
FINISHED = ("Completed", "Cancelled")


def reconcile_project_progress() -> list[str]:
	"""Recount every Project whose stored percentage disagrees with its tasks."""
	counts = _task_counts()
	if not counts:
		return []

	corrected = []
	for project in frappe.get_all(
		"Project",
		filters={"percent_complete_method": ["in", ["Task Completion", ""]]},
		fields=["name", "status", "percent_complete"],
	):
		total, finished = counts.get(project.name, (0, 0))
		if not total:
			continue

		wanted = flt(flt(finished) / total * 100, 2)
		if flt(project.percent_complete, 2) == wanted:
			continue

		updates = {"percent_complete": wanted}
		# ERPNext drives the status from the percentage, so a project that is no longer
		# finished must not keep saying it is.
		if wanted < 100 and project.status == "Completed":
			updates["status"] = "Open"

		# Written straight to the row on purpose: these are derived display fields, and a
		# full save would fire the whole project hook chain on every migrate.
		frappe.db.set_value("Project", project.name, updates, update_modified=False)
		corrected.append(
			"%s: %s%% -> %s%% (%s of %s tasks finished)%s"
			% (project.name, project.percent_complete, wanted, finished, total,
			   ", status Completed -> Open" if "status" in updates else "")
		)

	if corrected:
		frappe.db.commit()
		frappe.log_error(
			title="CGM: project progress reconciled",
			message="\n".join(f"- {line}" for line in corrected),
		)

	return corrected


def _task_counts() -> dict[str, tuple[int, int]]:
	"""{project: (total tasks, tasks finished)} in one query."""
	rows = frappe.db.sql(
		"""
		SELECT project,
		       COUNT(name) AS total,
		       SUM(CASE WHEN status IN ('Completed', 'Cancelled') THEN 1 ELSE 0 END) AS finished
		FROM `tabTask`
		WHERE project IS NOT NULL AND project != ''
		GROUP BY project
		""",
		as_dict=True,
	)
	return {row.project: (row.total, int(row.finished or 0)) for row in rows}
