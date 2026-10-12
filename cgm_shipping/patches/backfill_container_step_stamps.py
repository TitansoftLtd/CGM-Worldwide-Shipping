"""Stamp the Container Step on the Sea Import template and its Tasks.

Why: container events, the container grid and its completion checks keyed on
step numbers from CGM Shipping Settings, so moving a template row misrouted them
- the grid columns were already one step off in production. The Container Step
stamp replaces the number.

What: sets CGM Task Template Item.container_step on the Sea Import rows whose
number matches a Settings container step (blank rows only), then stamps every
Sea Import Task with its own template row's step, matched by subject as the
template sync does.

Idempotent: only writes blanks and differing values; safe to re-run. One-time -
retire per docs/guides/patches.md once staging and production Patch Log show it.
"""

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CONTAINER_STEP_BY_SEQ_FIELD,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
		get_container_task_sequence,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		ensure_task_behaviour_fields,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_TEMPLATE,
		sea_import_flow_keys,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		template_item_for_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.task_engine import _collect_items

	# The Task field is otherwise created in after_migrate, which runs after patches.
	ensure_task_behaviour_fields()
	if not frappe.db.exists("CGM Task Template", SEA_IMPORT_TEMPLATE):
		return

	step_by_seq = {
		get_container_task_sequence(fieldname): step
		for fieldname, step in CONTAINER_STEP_BY_SEQ_FIELD.items()
	}
	template_rows = 0
	for row in frappe.get_all(
		"CGM Task Template Item",
		filters={"parent": SEA_IMPORT_TEMPLATE, "parenttype": "CGM Task Template"},
		fields=["name", "sequence_no", "container_step"],
	):
		step = step_by_seq.get(int(row.sequence_no or 0))
		if step and not row.container_step:
			frappe.db.set_value(
				"CGM Task Template Item", row.name, "container_step", step, update_modified=False
			)
			template_rows += 1

	items = _collect_items(frappe.get_doc("CGM Task Template", SEA_IMPORT_TEMPLATE))
	tasks = 0
	for task in frappe.get_all(
		"Task",
		filters={"custom_task_flow_key": ["in", sea_import_flow_keys()]},
		fields=["name", "subject", "custom_sequence_no", "custom_container_step"],
	):
		item = template_item_for_task(task, items)
		if not item:
			continue
		want = item.get("container_step") or ""
		if (task.custom_container_step or "") != want:
			frappe.db.set_value("Task", task.name, "custom_container_step", want, update_modified=False)
			tasks += 1

	print(f"Container Step: {template_rows} template rows, {tasks} Sea Import tasks stamped")
