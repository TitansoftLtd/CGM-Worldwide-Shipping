"""Make Portal Feedback a shipment-level record.

Feedback started out with a `reference_type` of Project or Container Tracker.
It is now always about a Project; where it concerns particular boxes, those go
in the `containers` child table instead of splitting the rating into a separate
per-container record.

Container-scoped rows are carried across rather than dropped: each becomes (or
folds into) the party's feedback on the parent shipment, with the container it
named ticked in the child table.
"""

from __future__ import annotations

import frappe

_DROPPED_COLUMNS = ("reference_type", "container_tracker", "container_number")


def execute() -> None:
	if not frappe.db.table_exists("Portal Feedback"):
		return

	columns = set(frappe.db.get_table_columns("Portal Feedback"))
	if "container_tracker" in columns:
		_migrate_container_rows()

	for column in _DROPPED_COLUMNS:
		if column in columns:
			frappe.db.sql_ddl(f"ALTER TABLE `tabPortal Feedback` DROP COLUMN `{column}`")

	frappe.clear_cache(doctype="Portal Feedback")
	frappe.db.commit()


def _migrate_container_rows() -> None:
	rows = frappe.db.sql(
		"""
		SELECT name, project, container_tracker, submitted_by, submitted_by_party
		FROM `tabPortal Feedback`
		WHERE IFNULL(container_tracker, '') != ''
		""",
		as_dict=True,
	)
	if not rows:
		return

	folded = 0
	for row in rows:
		project = row.project or frappe.db.get_value(
			"Container Tracker", row.container_tracker, "project"
		)
		if not project:
			continue

		# Does this party already have shipment-level feedback here? If so the
		# container row folds into it as a ticked container; otherwise the row
		# itself becomes the shipment-level one.
		existing = frappe.db.get_value(
			"Portal Feedback",
			{
				"project": project,
				"submitted_by": row.submitted_by,
				"submitted_by_party": row.submitted_by_party,
				"name": ("!=", row.name),
			},
			"name",
		)
		target = existing or row.name
		if not existing:
			frappe.db.set_value(
				"Portal Feedback", row.name, "project", project, update_modified=False
			)

		_append_container(target, row.container_tracker)

		if existing:
			frappe.delete_doc("Portal Feedback", row.name, force=True, ignore_permissions=True)
			folded += 1

	frappe.db.commit()
	print(f"Portal Feedback: moved {len(rows)} container rows to shipment level ({folded} folded).")


def _append_container(parent: str, container_tracker: str) -> None:
	if frappe.db.exists(
		"Portal Feedback Container",
		{"parent": parent, "parenttype": "Portal Feedback", "container_tracker": container_tracker},
	):
		return
	idx = (
		frappe.db.sql(
			"""SELECT IFNULL(MAX(idx), 0) FROM `tabPortal Feedback Container`
			   WHERE parent = %s AND parenttype = 'Portal Feedback'""",
			(parent,),
		)[0][0]
		or 0
	)
	child = frappe.new_doc("Portal Feedback Container")
	child.parent = parent
	child.parenttype = "Portal Feedback"
	child.parentfield = "containers"
	child.container_tracker = container_tracker
	child.container_number = frappe.db.get_value(
		"Container Tracker", container_tracker, "container_number"
	)
	child.idx = idx + 1
	child.insert(ignore_permissions=True)
