import base64
import io

import frappe
from pyqrcode import create as qrcreate


def get_doc_qr_code(doctype, docname):
	"""
	Generate a base64 PNG QR code for any ERPNext document.
	Registered via jinja.methods in hooks.py.

	Uses PyQRCode (shipped with Frappe) so no extra bench dependency is needed.

	Usage in any Jinja print format:
		{% set qr = get_doc_qr_code(doc.doctype, doc.name) %}
		{% if qr %}
		<img src="data:image/png;base64,{{ qr }}" width="80" height="80">
		{% endif %}
	"""
	doc = frappe.get_doc(doctype, docname)
	payload = _build_payload(doc)

	qr = qrcreate(payload, error="M")
	buf = io.BytesIO()
	qr.png(buf, scale=4, module_color=(139, 26, 26), background=[255, 255, 255])
	return base64.b64encode(buf.getvalue()).decode()


def _build_payload(doc):
	dt = doc.doctype

	if dt == "Quotation":
		return (
			f"CGM Quotation\n"
			f"No: {doc.name}\n"
			f"Customer: {doc.customer_name or doc.party_name}\n"
			f"Date: {doc.transaction_date}\n"
			f"Valid Till: {doc.valid_till or 'N/A'}\n"
			f"Total: {doc.grand_total} {doc.currency}"
		)

	if dt == "Sales Invoice":
		return (
			f"CGM Sales Invoice\n"
			f"No: {doc.name}\n"
			f"Customer: {doc.customer_name}\n"
			f"Date: {doc.posting_date}\n"
			f"Due Date: {doc.due_date or 'N/A'}\n"
			f"Total: {doc.grand_total} {doc.currency}\n"
			f"Status: {doc.status}"
		)

	if dt == "Sales Order":
		return (
			f"CGM Sales Order\n"
			f"No: {doc.name}\n"
			f"Customer: {doc.customer_name}\n"
			f"Date: {doc.transaction_date}\n"
			f"Total: {doc.grand_total} {doc.currency}\n"
			f"Status: {doc.status}"
		)

	if dt == "Delivery Note":
		return (
			f"CGM Delivery Note\n"
			f"No: {doc.name}\n"
			f"Customer: {doc.customer_name}\n"
			f"Date: {doc.posting_date}\n"
			f"Status: {doc.status}"
		)

	return f"{dt}: {doc.name}\nCompany: {getattr(doc, 'company', '')}"


get_doc_qr_code = frappe.whitelist(allow_guest=False)(get_doc_qr_code)
