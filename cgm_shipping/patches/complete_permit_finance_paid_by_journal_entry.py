"""Complete Permit Finance tasks whose permits were paid after their last save.

journal_entry_on_submit had no Permit Finance branch, so when Finance posted the
last permit Journal Entry nothing completed the task: it stayed Open in the list
while the form, healing it in a GET request that is never committed, showed
Completed (TASK-2026-01209, -01087, -00913 on production).

Runs the same completion the Journal Entry hook now runs, only for tasks that
meet the gate - every row invoice-verified with a posted Journal Entry.
Re-runnable: completed tasks no longer match.
"""

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		auto_complete_finance_permit_task,
		can_complete_finance_permit_task,
	)

	if not frappe.get_meta("Task").has_field("custom_task_role"):
		return
	names = frappe.get_all(
		"Task",
		filters={"custom_task_role": "Permit Finance", "status": ["not in", ["Completed", "Cancelled"]]},
		pluck="name",
	)
	completed = []
	for name in names:
		task = frappe.get_doc("Task", name)
		if can_complete_finance_permit_task(task) and auto_complete_finance_permit_task(task):
			completed.append(name)
	if completed:
		print(f"Completed Permit Finance tasks paid after their last save: {', '.join(completed)}")
