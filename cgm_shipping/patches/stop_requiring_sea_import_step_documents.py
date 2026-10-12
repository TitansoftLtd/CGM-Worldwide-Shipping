"""Stop requiring documents on Sea Import's Lodge Delivery Order and field clearance steps.

Why: require_sea_import_step_documents made "Lodge Delivery Order" need DO and
"Field Officers conduct clearance" need FIELD and Delivery Note, so their tasks
refused to complete until those were attached (TASK-2026-00042). Field officers
clear on the documents uploaded earlier in the shipment, and the DO is attached
when there is one - neither step is meant to block on an upload.

What: clears Required Document Types on those template rows when they still list
only those documents, clears the same stamp on the tasks made from them, and
removes the empty rows that patch added to their Task Documents. Rows with a file
are kept. Also drops the matching step 14 / 17 Document rows from Settings >
custom_sea_clearance_task_requirements, which the app defaults no longer carry.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe

# subject -> (Settings step number, document tokens it no longer requires)
STEPS = {
	"Lodge Delivery Order": (14, {"DO", "DELIVERY ORDER"}),
	"Field Officers conduct clearance": (17, {"FIELD", "DELIVERY NOTE", "DELIVERY_NOTE"}),
}


def _only(value, documents) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
		parse_required_document_types,
	)

	tokens = {token.upper() for token in parse_required_document_types(value)}
	return bool(tokens) and tokens <= documents


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
	steps = {_subject_key(subject): documents for subject, (_seq, documents) in STEPS.items()}

	for row in frappe.get_all(
		"CGM Task Template Item",
		filters={"parent": SEA_IMPORT_TEMPLATE, "parenttype": "CGM Task Template"},
		fields=["name", "subject", "required_document_types"],
	):
		documents = steps.get(_subject_key(row.subject))
		if documents and _only(row.required_document_types, documents):
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
		documents = steps.get(_subject_key(task.subject))
		if not documents or not _only(task.custom_required_document_types, documents):
			continue
		frappe.db.set_value("Task", task.name, "custom_required_document_types", "", update_modified=False)
		kept = 0
		for row in frappe.get_doc("Task", task.name).get(TASK_DOCUMENTS_FIELD) or []:
			if (row.document_type or "").upper() in documents and not primary_attachment(row):
				frappe.db.delete("Shipment Document", {"name": row.name})
				continue
			kept += 1
			if row.idx != kept:
				frappe.db.set_value("Shipment Document", row.name, "idx", kept, update_modified=False)
		cleared.append(task.name)
	if cleared:
		print(f"Sea Import tasks no longer requiring step documents: {len(cleared)}")

	if frappe.db.exists("DocType", "Sea Clearance Task Requirement Item"):
		for seq, documents in STEPS.values():
			for row in frappe.get_all(
				"Sea Clearance Task Requirement Item",
				filters={"parent": "CGM Shipping Settings", "requirement_type": "Document", "sequence_no": seq},
				fields=["name", "value"],
			):
				if (row.value or "").strip().upper() in documents:
					frappe.db.delete("Sea Clearance Task Requirement Item", {"name": row.name})
					frappe.clear_document_cache("CGM Shipping Settings", "CGM Shipping Settings")
