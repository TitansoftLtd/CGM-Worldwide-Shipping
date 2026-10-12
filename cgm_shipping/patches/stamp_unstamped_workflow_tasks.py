"""Stamp every workflow Task that still has no Task Role.

Why: behaviour used to fall back to Sea Import step numbers for tasks created
before the Task Role stamps. That fallback is being removed, so every task a
workflow created must carry its stamps. The template sync only reaches tasks whose
flow key is a template name; this also covers legacy flow keys.

What: for each non-cancelled Task with a flow key and no Task Role, copies the
role, payment kind, permit stage, container step, flags and required documents
from its template row (matched by subject, then sequence). A task no row matches
becomes Standard and is listed.

Idempotent: only blank roles are written. One-time - retire per
docs/guides/patches.md once staging and production Patch Log show it.
"""

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		normalize_template_name,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		template_item_for_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.task_engine import _collect_items

	meta = frappe.get_meta("Task")
	if not meta.has_field("custom_task_role"):
		return

	tasks = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": ["is", "set"],
			"custom_task_role": ["is", "not set"],
			"status": ["!=", "Cancelled"],
		},
		fields=["name", "subject", "custom_sequence_no", "custom_task_flow_key"],
	)
	if not tasks:
		return

	items_by_template: dict[str, list] = {}
	stamped, standard = [], []
	for task in tasks:
		template = normalize_template_name(task.custom_task_flow_key) or task.custom_task_flow_key
		if template not in items_by_template:
			items_by_template[template] = (
				_collect_items(frappe.get_doc("CGM Task Template", template))
				if frappe.db.exists("CGM Task Template", template)
				else []
			)
		item = template_item_for_task(task, items_by_template[template])
		if not item:
			frappe.db.set_value("Task", task.name, "custom_task_role", "Standard", update_modified=False)
			standard.append(task.name)
			continue
		values = {
			"custom_task_role": item.get("task_role") or "Standard",
			"custom_payment_kind": item.get("payment_kind") or "",
			"custom_permit_stage": item.get("permit_stage") or "",
			"custom_requires_finance_action": 1 if item.get("requires_finance_action") else 0,
			"custom_requires_document_upload": 1 if item.get("requires_document_upload") else 0,
			"custom_requires_permit_action": 1 if item.get("requires_permit_action") else 0,
			"custom_is_auto_completable": 1 if item.get("is_auto_completable") else 0,
		}
		if meta.has_field("custom_container_step"):
			values["custom_container_step"] = item.get("container_step") or ""
		if meta.has_field("custom_required_document_types"):
			values["custom_required_document_types"] = item.get("required_document_types") or ""
		frappe.db.set_value("Task", task.name, values, update_modified=False)
		stamped.append(task.name)

	print(
		f"Stamped {len(stamped)} unstamped workflow tasks from their template; "
		f"{len(standard)} matched no template row and became Standard: {', '.join(standard[:20])}"
	)
