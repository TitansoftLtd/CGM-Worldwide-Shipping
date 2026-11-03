"""One line per declaration, holding its invoice, its document and its receipt.

A UCR's three papers sat in two tables, and the certificate row is often absent
rather than empty, so "missing" could not be told apart from "not set up yet".
Permits put all three on one row; this gives UCR and Entry the same view.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	IDF_CERTIFICATE_CODES,
	TASK_DOCUMENTS_FIELD,
	TASK_FINANCE_FIELD,
)

STATE_ATTACHED = "attached"
STATE_MISSING = "missing"
# An amendment line has no document of its own; the declaration's one sits above it.
STATE_NOT_APPLICABLE = "n/a"


def _norm(code: str | None) -> str:
	return (code or "").strip().upper().replace(" ", "_")


def _accepted_document_codes(certificate_code: str) -> set[str]:
	"""The codes that count as this declaration's own document.

	A UCR's certificate lands under any of IDF, IDF CERT or UCR_CERT depending on
	when the row was made, so one code is not enough to tell attached from missing.
	"""
	normalised = _norm(certificate_code)
	family = {_norm(c) for c in IDF_CERTIFICATE_CODES}
	return family if normalised in family else {normalised}


def _document_code(document_type: str | None) -> str:
	if not document_type:
		return ""
	code = frappe.db.get_value("Document Type", document_type, "code")
	return _norm(code or document_type)


def _finance_rows(task, label: str) -> list:
	wanted = (label or "").strip()
	return [
		row
		for row in (task.get(TASK_FINANCE_FIELD) or [])
		if (row.get("line_label") or "").strip() == wanted
	]


def _document_rows(task, certificate_code: str) -> list:
	accepted = _accepted_document_codes(certificate_code)
	return [
		row
		for row in (task.get(TASK_DOCUMENTS_FIELD) or [])
		if _document_code(row.get("document_type")) in accepted
	]


def _slot(row, *fields: str) -> dict:
	"""What one cell shows: the newest file on the row, or that nothing is there."""
	if row is None:
		return {"state": STATE_MISSING, "file_url": "", "file_name": "", "verified": 0}
	url = ""
	for field in fields:
		value = (row.get(field) or "").strip()
		if value:
			url = value
			break
	return {
		"state": STATE_ATTACHED if url else STATE_MISSING,
		"file_url": url,
		"file_name": url.rsplit("/", 1)[-1] if url else "",
		"verified": 1 if (row.get("verified") or row.get("verified_by")) else 0,
	}


def _declaration_label(profile) -> str:
	""""UCR Invoice" names the paper; the declaration itself is just "UCR"."""
	label = (profile.invoice_label or "").strip()
	for suffix in (" Invoice",):
		if label.endswith(suffix):
			return label[: -len(suffix)]
	return label or profile.payment_item


def declaration_register(task) -> dict:
	"""Rows for the task's declaration, or nothing when it has no document of its own."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		profile_for_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		ROLE_APPLICATION,
	)

	profile = profile_for_task(task)
	# Only UCR and Entry have a document of their own, so only they were split over
	# two tables. KPA, CFS and Shipping Line keep both papers in one place already.
	if not profile or not profile.certificate_document_code:
		return {"rows": [], "missing": []}
	# The declarant's own task is where the document belongs. On the finance task
	# there is no document row to find, and a blank cell there would read as a gap
	# when finance was never meant to hold it.
	if (task.get("custom_task_role") or "").strip() != ROLE_APPLICATION:
		return {"rows": [], "missing": []}

	invoices = _finance_rows(task, profile.invoice_label)
	receipts = _finance_rows(task, profile.receipt_label)
	documents = _document_rows(task, profile.certificate_document_code)

	rows = []
	for index in range(max(len(invoices), len(receipts), 1)):
		invoice = invoices[index] if index < len(invoices) else None
		receipt = receipts[index] if index < len(receipts) else None
		# The declaration's own document belongs to the declaration, not to an
		# amendment of its invoice, so it sits on the first row only.
		if index == 0:
			document = _slot(documents[0] if documents else None, "final_attachment", "attachment")
		else:
			document = {"state": STATE_NOT_APPLICABLE, "file_url": "", "file_name": "", "verified": 0}
		rows.append(
			{
				"label": _declaration_label(profile),
				"amendment": bool(invoice.get("is_amendment")) if invoice else False,
				"invoice": _slot(invoice, "attachment"),
				"document": document,
				"receipt": _slot(receipt, "attachment"),
			}
		)

	missing = sorted(
		{
			name
			for row in rows
			for name, slot in (
				("Invoice", row["invoice"]),
				("Document", row["document"]),
				("Receipt", row["receipt"]),
			)
			if slot["state"] == STATE_MISSING
		}
	)

	return {
		"rows": rows,
		"missing": missing,
		"invoice_label": profile.invoice_label,
		"receipt_label": profile.receipt_label,
	}


@frappe.whitelist()
def get_task_declaration_register(task: str) -> dict:
	"""Whitelisted for the panel on the UCR and Entry tasks."""
	if not task:
		return {"rows": [], "missing": []}
	frappe.has_permission("Task", doc=task, throw=True)
	return declaration_register(frappe.get_doc("Task", task))
