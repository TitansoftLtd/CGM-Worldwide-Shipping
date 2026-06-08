"""Task Finance Lines table + IDF certificate on IDF UCR Record."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_shipment_fields import (
	_create_cf,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
	LINE_INVOICE,
	LINE_RECEIPT,
	PAYMENT_UCR,
	TASK_FINANCE_FIELD,
	UCR_INVOICE_LABEL,
	UCR_RECEIPT_LABEL,
	seed_ucr_finance_lines,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
	TASK_DOCUMENTS_FIELD,
	get_document_type_code,
	ensure_task_document_types,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	get_document_type_link_name,
)


def execute():
	frappe.reload_doc("cgm_worldwide_shipping", "doctype", "task_finance_line")
	frappe.reload_doc("cgm_worldwide_shipping", "doctype", "idf_ucr_record")

	_create_cf(
		"Task",
		{
			"fieldname": "custom_section_task_finance",
			"label": "Invoices & Receipts",
			"fieldtype": "Section Break",
			"insert_after": "custom_task_documents",
			"description": "",
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": TASK_FINANCE_FIELD,
			"label": "Invoices & Receipts",
			"fieldtype": "Table",
			"options": "Task Finance Line",
			"insert_after": "custom_section_task_finance",
		},
	)

	ensure_task_document_types()
	if frappe.db.exists("Custom Field", "Task-custom_section_break_0gs4o"):
		frappe.db.set_value(
			"Custom Field",
			"Task-custom_section_break_0gs4o",
			"label",
			"Clearance Documents",
			update_modified=False,
		)
	frappe.flags.cgm_skip_task_project_sync = True
	try:
		_migrate_ucr_invoice_rows_to_finance_lines()
		_seed_finance_lines_on_open_ucr_tasks()
	finally:
		frappe.flags.cgm_skip_task_project_sync = False
	frappe.clear_cache(doctype="Task")
	frappe.db.commit()


def _migrate_ucr_invoice_rows_to_finance_lines() -> None:
	"""Move UCR invoice attachments from Task Documents → Task Finance Lines."""
	if not frappe.db.exists("DocType", "Task Finance Line"):
		return

	legacy_codes = {"UCR_DOC", "UCR_INV", "UCR Invoice"}
	invoice_dt_names = set()
	for code in legacy_codes:
		name = get_document_type_link_name(code)
		if name:
			invoice_dt_names.add(name)

	if not invoice_dt_names:
		return

	tasks = frappe.get_all(
		"Task",
		filters={"custom_task_flow_key": "SEA_IMPORT_E2E", "custom_sequence_no": ("in", [3, 4])},
		pluck="name",
	)
	for task_name in tasks:
		task = frappe.get_doc("Task", task_name)
		if not task.meta.has_field(TASK_FINANCE_FIELD):
			continue
		seed_ucr_finance_lines(task)
		inv_line = None
		for row in task.get(TASK_FINANCE_FIELD) or []:
			if row.line_type == LINE_INVOICE:
				inv_line = row
				break
		if not inv_line:
			continue

		for doc_row in list(task.get(TASK_DOCUMENTS_FIELD) or []):
			if doc_row.document_type not in invoice_dt_names:
				continue
			if doc_row.attachment and not inv_line.attachment:
				inv_line.attachment = doc_row.attachment
			task.remove(doc_row)

		if int(task.get("custom_sequence_no") or 0) == 4:
			if task.get("custom_ucr_payment_receipt"):
				rec = None
				for row in task.get(TASK_FINANCE_FIELD) or []:
					if row.line_type == LINE_RECEIPT:
						rec = row
						break
				if rec and not rec.attachment:
					rec.attachment = task.custom_ucr_payment_receipt
			if task.get("custom_ucr_invoice_verified") and inv_line:
				inv_line.verified = 1
			if task.get("custom_ucr_receipt_verified"):
				for row in task.get(TASK_FINANCE_FIELD) or []:
					if row.line_type == LINE_RECEIPT:
						row.verified = 1

		# Ensure task 3 has IDF certificate row instead of invoice doc type.
		if int(task.get("custom_sequence_no") or 0) == 3:
			_ensure_idf_cert_document_row(task)

		task.save(ignore_permissions=True)


def _ensure_idf_cert_document_row(task) -> None:
	dt_name = get_document_type_link_name("IDF_CERT")
	if not dt_name:
		return
	existing = {r.document_type for r in task.get(TASK_DOCUMENTS_FIELD) or [] if r.document_type}
	if dt_name not in existing:
		task.append(TASK_DOCUMENTS_FIELD, {"document_type": dt_name, "status": "Missing"})


def _seed_finance_lines_on_open_ucr_tasks() -> None:
	for task_name in frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": "SEA_IMPORT_E2E",
			"custom_sequence_no": ("in", [3, 4]),
			"status": ("!=", "Cancelled"),
		},
		pluck="name",
	):
		task = frappe.get_doc("Task", task_name)
		if not task.meta.has_field(TASK_FINANCE_FIELD):
			continue
		seed_ucr_finance_lines(task)
		if int(task.get("custom_sequence_no") or 0) == 3:
			_ensure_idf_cert_document_row(task)
		task.save(ignore_permissions=True)
