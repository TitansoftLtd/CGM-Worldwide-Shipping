# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

PERMIT_REGISTER_ATTACHMENTS = (
	("payment_invoice", "invoice_uploaded_on", "invoice_uploaded_by"),
	("permit_document", "certificate_uploaded_on", "certificate_uploaded_by"),
)

SHIPMENT_DOCUMENT_ATTACHMENTS = (
	("draft_documents", "draft_documents_uploaded_on", "draft_documents_uploaded_by"),
	("final_attachment", "final_document_uploaded_on", "final_document_uploaded_by"),
)


def stamp_child_table_attachment_metadata(
	doc,
	table_fieldname: str,
	attachments: tuple[tuple[str, str, str], ...],
) -> None:
	"""Set upload audit fields when child-table attachments change on a parent save."""
	if not doc.meta.has_field(table_fieldname):
		return

	prev_by_name = _previous_child_rows(doc, table_fieldname)
	for row in doc.get(table_fieldname) or []:
		prev_row = prev_by_name.get(row.name)
		for attach_field, on_field, by_field in attachments:
			stamp_row_attachment_metadata(row, prev_row, attach_field, on_field, by_field)


def _previous_child_rows(doc, fieldname: str) -> dict[str, Document]:
	prev = doc.get_doc_before_save()
	if not prev or not prev.meta.has_field(fieldname):
		return {}
	return {row.name: row for row in prev.get(fieldname) or [] if row.name}


def stamp_row_attachment_metadata(
	row,
	prev_row,
	attach_field: str,
	on_field: str,
	by_field: str,
) -> None:
	current = (row.get(attach_field) or "").strip()
	previous = (prev_row.get(attach_field) or "").strip() if prev_row else ""

	if not current:
		if previous:
			setattr(row, on_field, None)
			setattr(row, by_field, None)
		return

	if current == previous:
		return

	setattr(row, on_field, now_datetime())
	setattr(row, by_field, frappe.session.user)
