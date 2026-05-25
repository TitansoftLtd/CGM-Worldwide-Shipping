"""Client documents vs permits on Shipment Dossier."""
from __future__ import annotations

import frappe
from frappe.utils import now_datetime

SHIPMENT_DOCUMENTS_FIELD = "shipment_documents"

# First documents from the client (attach here, not in Permit Register).
INTAKE_DOCUMENT_CODES = ("CI", "PKL")

SHIPMENT_TYPE_TO_MODE = {
	"Air Import": "Air",
	"Sea FCL": "Sea",
	"Sea LCL": "Sea",
	"Road Import": "Road",
	"Transit": "Road",
	"Export": "Sea",
}


def before_insert(doc, method=None):
	seed_client_document_checklist(doc)


def validate(doc, method=None):
	normalize_document_rows(doc)
	enforce_client_documents_before_documents_received(doc)


def seed_client_document_checklist(doc):
	"""Pre-fill Shipment Document rows from Document Type (Commercial Invoice, Packing List, etc.)."""
	mode = SHIPMENT_TYPE_TO_MODE.get(doc.shipment_type)
	if not mode:
		return

	rows = doc.get(SHIPMENT_DOCUMENTS_FIELD) or []
	existing = {r.document_type for r in rows if r.document_type}

	filters = {"default_required": 1}
	filters["mode_of_transport"] = ["in", [mode, "", None]]

	for dt in frappe.get_all(
		"Document Type",
		filters=filters,
		fields=["name", "code", "required_stage"],
		order_by="required_stage asc, name asc",
	):
		if dt.name in existing:
			continue
		doc.append(
			SHIPMENT_DOCUMENTS_FIELD,
			{
				"document_type": dt.name,
				"status": "Missing",
			},
		)


def normalize_document_rows(doc):
	for row in doc.get(SHIPMENT_DOCUMENTS_FIELD) or []:
		if row.attachment:
			if row.status in (None, "", "Missing"):
				row.status = "Uploaded"
			if not row.uploaded_by:
				row.uploaded_by = frappe.session.user
			if not row.uploaded_on:
				row.uploaded_on = now_datetime()
		else:
			row.status = "Missing"
			row.uploaded_by = None
			row.uploaded_on = None
			row.verified_by = None
			row.verified_on = None

		if row.status in ("Verified", "Rejected"):
			if not row.attachment:
				frappe.throw(
					f"Attach a file before marking {row.document_type or 'document'} as {row.status}."
				)
			if not row.verified_by:
				row.verified_by = frappe.session.user
			if not row.verified_on:
				row.verified_on = now_datetime()


def enforce_client_documents_before_documents_received(doc):
	"""Block workflow move to Documents Received until CI + PKL are uploaded."""
	prev = doc.get_doc_before_save()
	if not prev or prev.status == doc.status:
		return
	if doc.status != "Documents Received":
		return

	missing = _missing_intake_documents(doc)
	if missing:
		labels = ", ".join(missing)
		frappe.throw(
			f"Upload client documents in <b>Client Documents</b> before receiving the file: {labels}. "
			"Commercial Invoice and Packing List belong there — not in Permit Register."
		)


def _missing_intake_documents(doc):
	missing = []
	rows_by_code = {}
	for row in doc.get(SHIPMENT_DOCUMENTS_FIELD) or []:
		if not row.document_type:
			continue
		code = frappe.db.get_value("Document Type", row.document_type, "code")
		if code:
			rows_by_code[code] = row

	for code in INTAKE_DOCUMENT_CODES:
		row = rows_by_code.get(code)
		if not row or not row.attachment or row.status == "Missing":
			label = frappe.db.get_value("Document Type", {"code": code}, "name") or code
			missing.append(label)
	return missing
