"""Put the progress bar at 100% on shipments whose tasks are all done.

Why: the transport steps are completed from the Container Tracker, which writes
the status with `frappe.db.set_value` for speed. That skips document hooks, so
ERPNext's `Task.update_project()` never fired and the Project kept whatever
percentage it had before. A shipment whose last two steps auto-completed then sat
below 100% with every task closed - PROJ-0039 showed 91.3% (21 of 23) three days
after its final task completed, and PROJ-0003 showed 87%.

CGM's own `custom_shipment_status` was right the whole time, because
`sync_project_shipment_status_from_tasks` does run on that path. Only ERPNext's
rollup was stale, which is why the two fields disagreed and a finished shipment
still read as in progress.

What: finds projects where every task is Completed or Cancelled but the bar is
below 100%, and recomputes it through ERPNext's own `Project.update_project()`.

Deliberately one-directional. Recomputing every drifted project would also pull
some *down* - two shipments currently read 100% with 20 of 23 tasks done - and a
project that reads finished suddenly reading incomplete is a conversation to have
on purpose, not a side effect of a cleanup patch. Those are left alone here.

This changes a percentage and nothing else. No task is completed, no status is
changed, and `Project.status` is untouched - CGM does not manage that field.

The cause is fixed in `_auto_complete_container_task`, so this is a one-off
cleanup for projects that drifted before that fix shipped.

Idempotent. Retire per docs/guides/patches.md once staging and production Patch
Log show it.
"""

import frappe


def _fully_completed_projects() -> list[str]:
	"""Projects whose every task is Completed or Cancelled."""
	rows = frappe.db.sql(
		"""
		select project
		from `tabTask`
		where ifnull(project, '') != ''
		group by project
		having count(name) = sum(case when status in ('Completed', 'Cancelled') then 1 else 0 end)
		""",
		as_dict=True,
	)
	return [r.project for r in rows]


def execute():
	names = _fully_completed_projects()
	if not names:
		print("No fully completed projects; nothing to recompute.")
		return

	projects = frappe.get_all(
		"Project",
		filters={"name": ["in", names]},
		fields=["name", "percent_complete", "percent_complete_method"],
		order_by="name",
	)

	raised, skipped, failed = [], 0, 0
	for project in projects:
		# Manual projects carry a figure somebody typed; do not overwrite it.
		if (project.percent_complete_method or "Task Completion") == "Manual":
			skipped += 1
			continue

		before = round(float(project.percent_complete or 0), 2)
		if before >= 100:
			skipped += 1
			continue

		try:
			# ERPNext's own rollup, so this cannot disagree with what the app would
			# compute on the next ordinary task save.
			frappe.get_doc("Project", project.name).update_project()
		except Exception:
			frappe.log_error(
				title="refresh_stale_project_percent_complete",
				message=f"{project.name}: {frappe.get_traceback()}",
			)
			failed += 1
			continue

		after = round(float(frappe.db.get_value("Project", project.name, "percent_complete") or 0), 2)
		raised.append((project.name, before, after))

	frappe.db.commit()

	print(
		f"Fully completed projects: {len(projects)}; bar raised: {len(raised)}; "
		f"already correct: {skipped}; could not recompute: {failed}"
	)
	for name, before, after in raised:
		print(f"  {name}: {before}% -> {after}%")
