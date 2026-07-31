"""Keep only application↔finance depends_on links on sea import tasks.

Non-finance steps (inspection, Lodge DO, field clearance, transport, …) become
independent so teams can work them in parallel. Idempotent.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	SEA_IMPORT_TEMPLATE,
	sea_import_flow_keys,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	sea_import_tasks,
)


def _sync_sea_import_template_depends() -> None:
	if not frappe.db.exists("DocType", "CGM Task Template"):
		return
	if not frappe.db.exists("CGM Task Template", SEA_IMPORT_TEMPLATE):
		return

	desired = {
		int(row["sequence_no"]): (row.get("depends_on_sequences") or "").strip()
		for row in sea_import_tasks()
	}
	doc = frappe.get_doc("CGM Task Template", SEA_IMPORT_TEMPLATE)
	changed = False
	for row in doc.tasks or []:
		seq = int(row.sequence_no or 0)
		if seq not in desired:
			continue
		new_deps = desired[seq]
		if (row.depends_on_sequences or "").strip() != new_deps:
			row.depends_on_sequences = new_deps
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _rebuild_project_task_depends(project: str, tasks_by_seq: dict[int, str], pairs: dict[int, int]) -> None:
	"""Clear all depends_on on sea tasks, then re-link finance → application only."""
	for seq, task_name in tasks_by_seq.items():
		frappe.db.delete("Task Depends On", {"parent": task_name, "parenttype": "Task"})
		app_seq = pairs.get(seq)
		if not app_seq:
			frappe.db.set_value("Task", task_name, "depends_on_tasks", "", update_modified=False)
			continue
		app_name = tasks_by_seq.get(app_seq)
		if not app_name:
			frappe.db.set_value("Task", task_name, "depends_on_tasks", "", update_modified=False)
			continue
		row = frappe.get_doc(
			{
				"doctype": "Task Depends On",
				"parent": task_name,
				"parenttype": "Task",
				"parentfield": "depends_on",
				"task": app_name,
				"subject": frappe.db.get_value("Task", app_name, "subject") or "",
			}
		)
		row.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Task",
			task_name,
			"depends_on_tasks",
			f"{app_name},",
			update_modified=False,
		)


def _relink_existing_sea_projects() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		sea_finance_dependency_pairs,
	)

	pairs = {fin: app for app, fin in sea_finance_dependency_pairs()}
	flow_keys = tuple(sea_import_flow_keys())
	if not flow_keys:
		return

	projects = frappe.db.sql(
		"""
		SELECT DISTINCT project
		FROM `tabTask`
		WHERE project IS NOT NULL
		  AND custom_task_flow_key IN %s
		""",
		(flow_keys,),
		as_dict=True,
	)
	for row in projects:
		project = row.project
		tasks = frappe.db.sql(
			"""
			SELECT name, custom_sequence_no AS seq
			FROM `tabTask`
			WHERE project = %s
			  AND custom_task_flow_key IN %s
			  AND custom_sequence_no IS NOT NULL
			""",
			(project, flow_keys),
			as_dict=True,
		)
		tasks_by_seq = {int(t.seq): t.name for t in tasks if t.seq}
		if not tasks_by_seq:
			continue
		_rebuild_project_task_depends(project, tasks_by_seq, pairs)


def execute():
	_sync_sea_import_template_depends()
	_relink_existing_sea_projects()
	frappe.clear_cache()
