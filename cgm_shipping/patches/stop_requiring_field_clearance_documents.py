"""Stop requiring documents on Sea Import's field clearance step.

Why: require_sea_import_step_documents made "Field Officers conduct clearance"
need FIELD and Delivery Note, so its tasks refused to complete until both were
attached (TASK-2026-00042). Field officers clear on the documents uploaded
earlier in the shipment; the step was never meant to ask for an upload.

What: clears Required Document Types on that template row when it still lists
only those documents, clears the same stamp on the tasks made from it, and
removes the empty FIELD / Delivery Note rows that patch added to their Task
Documents. Rows with a file are kept. Also drops the step 17 FIELD /
DELIVERY_NOTE rows from Settings > custom_sea_clearance_task_requirements, which
the app defaults no longer carry.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe

SUBJECT = "Field Officers conduct clearance"
DOCUMENTS = {"FIELD", "DELIVERY NOTE", "DELIVERY_NOTE"}
SETTINGS_STEP = 17


def _only_field_clearance_documents(value) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
		parse_required_document_types,
	)

	tokens = {token.upper() for token in parse_required_document_types(value)}
	return bool(tokens) and tokens <= DOCUMENTS


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_DOCUMENTS_FIELD
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import primary_attachment
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_TEMPLATE,
		sea_import_flow_keys,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import _subject_key

	if not frappe.db.exists("CGM Task Template", SEA_IMPORT_TEMPLATE):
		return

	for row in frappe.get_all(
		"CGM Task Template Item",
		filters={"parent": SEA_IMPORT_TEMPLATE, "parenttype": "CGM Task Template"},
		fields=["name", "subject", "required_document_types"],
	):
		if _subject_key(row.subject) == _subject_key(SUBJECT) and _only_field_clearance_documents(
			row.required_document_types
		):
			frappe.db.set_value(
				"CGM Task Template Item", row.name, "required_document_types", "", update_modified=False
			)
			frappe.clear_document_cache("CGM Task Template", SEA_IMPORT_TEMPLATE)

	cleared = []
	for task in frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": ["in", list(sea_import_flow_keys())],
			"custom_required_document_types": ["is", "set"],
		},
		fields=["name", "subject", "custom_required_document_types"],
	):
		if _subject_key(task.subject) != _subject_key(SUBJECT):
			continue
		if not _only_field_clearance_documents(task.custom_required_document_types):
			continue
		frappe.db.set_value("Task", task.name, "custom_required_document_types", "", update_modified=False)
		rows = frappe.get_doc("Task", task.name).get(TASK_DOCUMENTS_FIELD) or []
		kept = 0
		for row in rows:
			if (row.document_type or "").upper() in DOCUMENTS and not primary_attachment(row):
				frappe.db.delete("Shipment Document", {"name": row.name})
				continue
			kept += 1
			if row.idx != kept:
				frappe.db.set_value("Shipment Document", row.name, "idx", kept, update_modified=False)
		cleared.append(task.name)
	if cleared:
		print(f"Field clearance tasks no longer require documents: {len(cleared)}")

	if frappe.db.table_exists("Sea Clearance Task Requirement Item"):
		for row in frappe.get_all(
			"Sea Clearance Task Requirement Item",
			filters={
				"parent": "CGM Shipping Settings",
				"requirement_type": "Document",
				"sequence_no": SETTINGS_STEP,
			},
			fields=["name", "value"],
		):
			if (row.value or "").strip().upper() in DOCUMENTS:
				frappe.db.delete("Sea Clearance Task Requirement Item", {"name": row.name})
				frappe.clear_document_cache("CGM Shipping Settings", "CGM Shipping Settings")
