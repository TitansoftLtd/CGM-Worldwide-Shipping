"""Require the Delivery Order on Sea Import's Lodge Delivery Order step, and the
field report and delivery note on its field clearance step.

Why: CGM Shipping Settings asked for them by step number (14 and 17), which only
tasks created before the Task Role stamps still read, so tasks from the template
no longer enforced them. They now sit in the template rows' Required Document
Types, where they show and can be edited.

What: sets Required Document Types on the Sea Import rows "Lodge Delivery Order"
(DO) and "Field Officers conduct clearance" (FIELD, Delivery Note) when blank,
then stamps the open tasks made from those rows and adds their Task Documents
rows. Completed and cancelled tasks are left as they are.

Idempotent: a row that already lists documents is left alone. One-time - retire
per docs/guides/patches.md once staging and production Patch Log show it.
"""

import frappe

REQUIRED = {
	"Lodge Delivery Order": ("DO",),
	"Field Officers conduct clearance": ("FIELD", "Delivery Note"),
}


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		ensure_stamped_required_documents_saved,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_TEMPLATE,
		sea_import_flow_keys,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		_subject_key,
		template_item_for_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
		serialize_required_document_types,
	)
	from cgm_shipping.cgm_worldwide_shipping.task_engine import _collect_items

	if not frappe.db.exists("CGM Task Template", SEA_IMPORT_TEMPLATE):
		return

	wanted = {
		_subject_key(subject): serialize_required_document_types(
			[name for name in names if frappe.db.exists("Document Type", name)]
		)
		for subject, names in REQUIRED.items()
	}
	changed: set[str] = set()
	for row in frappe.get_all(
		"CGM Task Template Item",
		filters={"parent": SEA_IMPORT_TEMPLATE, "parenttype": "CGM Task Template"},
		fields=["name", "subject", "required_document_types"],
	):
		key = _subject_key(row.subject)
		value = wanted.get(key)
		if not value or (row.required_document_types or "").strip():
			continue
		frappe.db.set_value(
			"CGM Task Template Item", row.name, "required_document_types", value, update_modified=False
		)
		changed.add(key)
	if not changed:
		return

	frappe.clear_document_cache("CGM Task Template", SEA_IMPORT_TEMPLATE)
	items = _collect_items(frappe.get_doc("CGM Task Template", SEA_IMPORT_TEMPLATE))
	stamped = []
	for task in frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": ["in", list(sea_import_flow_keys())],
			"status": ["not in", ["Completed", "Cancelled"]],
		},
		fields=["name", "subject", "custom_sequence_no"],
	):
		item = template_item_for_task(task, items)
		if not item or _subject_key(item.get("subject")) not in changed:
			continue
		frappe.db.set_value(
			"Task",
			task.name,
			"custom_required_document_types",
			item.get("required_document_types") or "",
			update_modified=False,
		)
		ensure_stamped_required_documents_saved(frappe.get_doc("Task", task.name))
		stamped.append(task.name)
	print(f"Sea Import step documents: {len(changed)} template rows, {len(stamped)} open tasks stamped")
