import frappe
from frappe.utils import now_datetime


def apply_shipment_document_automation(doc, _method=None):
	"""Keep Shipment Documents rows consistent before save."""
	for row in doc.get("custom_shipment_documents") or []:
		# Step 1: keep required synced from the linked document type.
		if row.document_type:
			default_required = frappe.db.get_value("Document Type", row.document_type, "default_required")
			if default_required is not None:
				row.required = int(default_required)

		# Step 2: auto-manage upload state and uploader metadata.
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

		# Step 3: keep verification metadata in sync with verification decisions.
		if row.status in ("Verified", "Rejected"):
			if not row.attachment:
				frappe.throw(f"Attach a file before marking {row.document_type or 'a document'} as {row.status}.")
			if not row.verified_by:
				row.verified_by = frappe.session.user
			if not row.verified_on:
				row.verified_on = now_datetime()
		elif row.status == "Uploaded":
			row.verified_by = None
			row.verified_on = None
