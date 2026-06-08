"""Remove UCR Invoice from Task Documents; invoices live on Task Finance Lines only."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
	ensure_task_document_types,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
	migrate_invoice_attachments_to_finance_lines_sql,
	prepare_ucr_task_tables,
	purge_all_invoice_clearance_document_rows,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	get_document_type_link_name,
)


def execute():
	ensure_task_document_types()
	migrate_invoice_attachments_to_finance_lines_sql()
	purge_all_invoice_clearance_document_rows()
	_rebuild_ucr_tasks()
	_retire_invoice_document_types()
	frappe.clear_cache(doctype="Document Type")
	frappe.clear_cache(doctype="Task")
	frappe.db.commit()


def _rebuild_ucr_tasks() -> None:
	frappe.flags.cgm_skip_task_project_sync = True
	try:
		for task_name in frappe.get_all(
			"Task",
			filters={"custom_task_flow_key": "SEA_IMPORT_E2E", "custom_sequence_no": ("in", [3, 4])},
			pluck="name",
		):
			task = frappe.get_doc("Task", task_name)
			prepare_ucr_task_tables(task)
			task.flags.ignore_links = True
			try:
				task.save(ignore_permissions=True)
			finally:
				task.flags.ignore_links = False
	finally:
		frappe.flags.cgm_skip_task_project_sync = False


def _retire_invoice_document_types() -> None:
	for code in ("UCR Invoice", "UCR_DOC", "UCR_INV"):
		name = frappe.db.get_value("Document Type", {"code": code}, "name") or (
			code if frappe.db.exists("Document Type", code) else None
		)
		if not name:
			continue
		doc = frappe.get_doc("Document Type", name)
		if doc.docstatus == 1:
			doc.cancel()
		if doc.docstatus == 0:
			frappe.delete_doc("Document Type", name, force=1, ignore_permissions=True)

	if not get_document_type_link_name("IDF_CERT"):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
			TASK_DOCUMENT_TYPE_DEFAULTS,
		)

		defaults = TASK_DOCUMENT_TYPE_DEFAULTS.get("IDF_CERT", {})
		doc = frappe.new_doc("Document Type")
		doc.code = "IDF_CERT"
		for key, value in defaults.items():
			setattr(doc, key, value)
		doc.insert(ignore_permissions=True)
		if doc.meta.is_submittable and doc.docstatus == 0:
			doc.submit()
