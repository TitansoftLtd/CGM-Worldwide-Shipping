"""Remove intake/project documents wrongly seeded on non-Document tasks.

Sea Import uses sequence 8 as Document Checkpoint in global settings; Transit
Import uses sequence 8 for Finance Payment. Legacy seq-only seeding copied BL /
COO / COA onto finance tasks — strip those rows now that routing is role-based.
"""

from __future__ import annotations

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		purge_unrequired_task_document_rows,
	)

	if not frappe.get_meta("Task").has_field("custom_task_documents"):
		return

	task_names = frappe.db.sql(
		"""
		SELECT DISTINCT parent
		FROM `tabShipment Document`
		WHERE parenttype = 'Task'
		""",
		pluck=True,
	)
	for task_name in task_names:
		task = frappe.get_doc("Task", task_name)
		if not purge_unrequired_task_document_rows(task):
			continue
		task.flags.ignore_validate = True
		task.save(ignore_permissions=True)
