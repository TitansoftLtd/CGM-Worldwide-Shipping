"""Reopen tasks the intake auto-complete closed by mistake.

Why: at project creation the intake auto-complete used Sea Import's steps (1 and
2) for Sea Transit Import too, so every Sea Transit project had step 2 (Request
shipping line charges from B/L) marked Completed, with the auto-complete note
written over its instructions. Intake steps now come from the template.

What: finds Completed tasks still carrying the auto-complete note whose template
row is not marked Complete When Client Documents Are In, sets them back to Open,
restores the row's instructions and leaves a comment saying why.

Idempotent: a reopened task no longer carries the note. One-time - retire per
docs/guides/patches.md once staging and production Patch Log show it.
"""

import frappe

REOPEN_COMMENT = (
	"Reopened: this step was marked Completed at project creation by mistake. "
	"Only the template's intake steps complete automatically when the client's documents are in."
)


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		AUTO_COMPLETE_INTAKE_REMARK,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		workflow_flow_keys_for_template,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		template_item_for_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.task_engine import _collect_items

	if not frappe.get_meta("CGM Task Template Item").has_field("completes_on_intake"):
		return

	reopened = []
	for template in frappe.get_all("CGM Task Template", pluck="name"):
		tasks = frappe.get_all(
			"Task",
			filters={
				"custom_task_flow_key": ["in", list(workflow_flow_keys_for_template(template))],
				"status": "Completed",
				"description": AUTO_COMPLETE_INTAKE_REMARK,
			},
			fields=["name", "subject", "custom_sequence_no", "project"],
		)
		if not tasks:
			continue
		items = _collect_items(frappe.get_doc("CGM Task Template", template))
		for task in tasks:
			item = template_item_for_task(task, items)
			if not item or item.get("completes_on_intake"):
				continue
			frappe.db.set_value(
				"Task",
				task.name,
				{
					"status": "Open",
					"completed_by": None,
					"completed_on": None,
					"description": item.get("description") or "",
				},
			)
			frappe.get_doc("Task", task.name).add_comment("Comment", REOPEN_COMMENT)
			reopened.append(f"{task.project} {task.name}")
	print(f"Reopened {len(reopened)} tasks closed by the intake auto-complete: {', '.join(reopened) or 'none'}")
