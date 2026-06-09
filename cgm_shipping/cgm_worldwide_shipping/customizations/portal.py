# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Shared data layer for the CGM customer portal.

The portal lets a customer (consignee) track their own shipments. A
shipment is a `Project`; granular tracking lives on `Container Tracker`
rows linked to the project, and the customer-vetted paperwork lives on
the project's `custom_shipment_documents` child table (Shipment Document).

Everything customer-facing is resolved through `customer_for_user`, which
maps the logged-in Website User to a single Customer via the standard
`Customer.portal_users` child table (with a Contact-link fallback). Every
query is scoped to that customer; detail/download endpoints re-verify
ownership server-side because URL parameters are untrusted.

Portal pages use `frappe.get_all` / `frappe.db.*` (which default to
ignoring permissions) so Website Users - who hold no desk read perm on
Project or Container Tracker - can still see their own shipments.
"""

from __future__ import annotations

from urllib.parse import quote

import frappe
from frappe import _

# ─── Customer resolution ─────────────────────────────────────────────────────


def customer_for_user(user: str | None = None) -> str | None:
	"""Resolve the Customer linked to a portal user.

	Primary: the standard `Customer.portal_users` child table (doctype
	"Portal User"), mirroring how the Imagine supplier portal links
	Suppliers. Fallback: a Contact tied to this User (by `user` or
	`email_id`) that links to a Customer via Dynamic Link - this covers
	customers onboarded through ERPNext's stock contact flow before a
	Portal User row exists. Returns None when nothing matches.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return None

	rows = frappe.get_all(
		"Portal User",
		filters={"user": user, "parenttype": "Customer"},
		fields=["parent"],
		limit=1,
	)
	if rows:
		return rows[0].parent

	contact = frappe.db.get_value("Contact", {"user": user}, "name") or frappe.db.get_value(
		"Contact", {"email_id": user}, "name"
	)
	if contact:
		linked = frappe.db.get_value(
			"Dynamic Link",
			{
				"parent": contact,
				"parenttype": "Contact",
				"link_doctype": "Customer",
			},
			"link_name",
		)
		if linked:
			return linked
	return None


def customer_display_name(customer: str | None) -> str:
	"""Human-friendly customer label (customer_name, falling back to id)."""
	if not customer:
		return ""
	return frappe.db.get_value("Customer", customer, "customer_name") or customer


# ─── Shipment lifecycle model ────────────────────────────────────────────────

# The granular Project.custom_shipment_status chart (18 ordered states).
SHIPMENT_STAGES = [
	"Draft",
	"Documents Received",
	"UCR Applied",
	"UCR Paid",
	"Pre-clearance",
	"Client Inspection",
	"In Transit",
	"Final Docs Received",
	"Manifest Requested",
	"Entry Lodged",
	"Line Paid & DO Lodged",
	"Entry Paid",
	"Post-clearance",
	"Field Clearance",
	"KPA Paid",
	"In Delivery",
	"Containers Returned",
	"Completed",
]
_STAGE_INDEX = {name: i for i, name in enumerate(SHIPMENT_STAGES)}

# Customer-facing milestones: the 18 internal states rolled up into six
# steps a consignee actually cares about. Each milestone owns a contiguous
# slice of the chart; a shipment's current milestone is whichever slice its
# status falls into.
MILESTONES = [
	("Booking & Documents", ("Draft", "Documents Received", "UCR Applied", "UCR Paid")),
	("Pre-Clearance", ("Pre-clearance", "Client Inspection")),
	("In Transit", ("In Transit",)),
	(
		"Arrival & Customs Entry",
		(
			"Final Docs Received",
			"Manifest Requested",
			"Entry Lodged",
			"Line Paid & DO Lodged",
			"Entry Paid",
		),
	),
	("Clearance", ("Post-clearance", "Field Clearance", "KPA Paid")),
	("Delivery", ("In Delivery", "Containers Returned", "Completed")),
]


def _milestone_index_for_status(status: str | None) -> int:
	"""Which milestone (0-5) the granular status belongs to. Defaults to 0."""
	for i, (_label, states) in enumerate(MILESTONES):
		if status in states:
			return i
	return 0


def shipment_progress(status: str | None) -> dict:
	"""Build the milestone stepper model for a shipment status.

	Returns a dict with:
	  - ``steps``: list of {label, state} where state is
	    'done' | 'current' | 'upcoming'
	  - ``current_label``: the friendly milestone label
	  - ``status``: the raw granular status (e.g. "Entry Lodged")
	  - ``percent``: 0-100 completion across the 18-state chart
	  - ``is_complete``: True once the shipment reaches "Completed"
	"""
	status = status or "Draft"
	current_ms = _milestone_index_for_status(status)
	is_complete = status == "Completed"

	steps = []
	for i, (label, _states) in enumerate(MILESTONES):
		if is_complete:
			state = "done"
		elif i < current_ms:
			state = "done"
		elif i == current_ms:
			state = "current"
		else:
			state = "upcoming"
		steps.append({"label": label, "state": state})

	# Percent across the granular chart so the bar advances within a
	# milestone too, not just between milestones.
	idx = _STAGE_INDEX.get(status, 0)
	last = len(SHIPMENT_STAGES) - 1
	percent = round(100 * idx / last) if last else 0

	return {
		"steps": steps,
		"current_label": MILESTONES[current_ms][0],
		"status": status,
		"percent": percent,
		"is_complete": is_complete,
	}


def status_tone(status: str | None) -> str:
	"""CSS tone class for a shipment status pill on lists/cards."""
	if not status or status == "Draft":
		return "muted"
	if status == "Completed":
		return "success"
	if status in ("In Transit", "In Delivery"):
		return "info"
	if status in ("Containers Returned",):
		return "primary"
	return "active"


# ─── Shipment queries ────────────────────────────────────────────────────────

# Fields pulled for the list / dashboard. Kept in one place so the list
# page, dashboard and detail header stay consistent.
SHIPMENT_LIST_FIELDS = [
	"name",
	"custom_cgm_ref_no",
	"custom_consignee",
	"custom_shipment_status",
	"custom_mode_of_transport",
	"custom_current_location",
	"custom_bl_number",
	"custom_batch_no",
	"custom_eta",
	"custom_ata",
	"custom_vessel_flight",
	"custom_delivery_type",
	"modified",
]


def get_customer_shipments(customer: str, limit: int = 200) -> list[dict]:
	"""All non-Draft shipments for a customer, newest activity first.

	Draft projects are internal staging records the customer shouldn't see
	yet, so they're filtered out (matching how internal tooling treats
	pre-confirmation shipments).
	"""
	if not customer:
		return []
	return frappe.get_all(
		"Project",
		filters={
			"customer": customer,
			"custom_shipment_status": ["!=", "Draft"],
		},
		fields=SHIPMENT_LIST_FIELDS,
		order_by="modified desc",
		limit=limit,
	)


def get_shipment_for_customer(project_name: str, customer: str) -> dict | None:
	"""Fetch a single shipment, enforcing customer ownership.

	Returns None when the project doesn't exist or belongs to another
	customer - callers render a "not authorized" state rather than leaking
	existence.
	"""
	if not project_name or not customer:
		return None
	row = frappe.db.get_value(
		"Project",
		project_name,
		[
			"name",
			"customer",
			"custom_cgm_ref_no",
			"custom_consignee",
			"custom_shipment_status",
			"custom_mode_of_transport",
			"custom_current_location",
			"custom_berth_phase",
			"custom_bl_number",
			"custom_batch_no",
			"custom_awb_number",
			"custom_do_reference",
			"custom_entry_no",
			"custom_vessel_flight",
			"custom_eta",
			"custom_ata",
			"custom_cfs",
			"custom_clearance_station_code",
			"custom_delivery_type",
			"custom_shipment_type",
			"custom_shipment_description",
			"custom_shipment_quantity",
			"custom_gross_weightkg",
			"custom_net_weightkg",
			"modified",
		],
		as_dict=True,
	)
	if not row or row.customer != customer:
		return None
	return row


def get_containers_for_shipment(project_name: str) -> list[dict]:
	"""Container Tracker rows for a shipment, ordered by container number."""
	if not project_name:
		return []
	return frappe.get_all(
		"Container Tracker",
		filters={"project": project_name},
		fields=[
			"name",
			"container_number",
			"container_mode",
			"status",
			"current_location",
			"delivery_location",
			"eta",
			"ata",
			"discharging_date",
			"custom_release_date",
			"gate_out_date_port",
			"icd_gate_out_date",
			"gate_in_date_warehouse",
			"offloading_date",
			"delivery_date",
			"border_clearance_date",
			"truck_number",
			"actual_empty_return",
			"demurrage_days",
			"demurrage_amount",
			"detention_days",
			"detention_amount",
			"days_outstanding",
		],
		order_by="container_number asc",
	)


# Customer-facing checkpoints derived from Container Tracker date fields.
# Order matters - this is the chronological journey of a box. Labels are
# translated at call time (in container_timeline), not at import, so they
# follow the request language rather than freezing at module load.
CONTAINER_CHECKPOINTS = [
	("eta", "Estimated Arrival"),
	("ata", "Arrived at Port"),
	("discharging_date", "Discharged"),
	("custom_release_date", "Customs Released"),
	("gate_out_date_port", "Gated Out (Port)"),
	("icd_gate_out_date", "Gated Out (ICD)"),
	("border_clearance_date", "Border Cleared"),
	("gate_in_date_warehouse", "Arrived at Warehouse"),
	("offloading_date", "Offloaded"),
	("delivery_date", "Delivered"),
	("actual_empty_return", "Empty Returned"),
]


def container_timeline(container: dict) -> list[dict]:
	"""Chronological checkpoint list for one container.

	Each entry is {label, date, done}. A checkpoint is 'done' once its
	date field is populated. Returns every checkpoint so the customer sees
	the whole journey, with the not-yet-reached ones greyed out.
	"""
	timeline = []
	for field, label in CONTAINER_CHECKPOINTS:
		value = container.get(field)
		timeline.append({"label": _(label), "date": value, "done": bool(value)})
	return timeline


# ─── Quotations & Sales Invoices ─────────────────────────────────────────────


def get_customer_quotations(customer: str, limit: int = 200) -> list[dict]:
	"""Sales Quotations addressed to this customer, newest first.

	Quotations link to a party via (quotation_to, party_name); we only
	want the ones raised to this Customer. Cancelled quotations (docstatus
	2) are hidden. Each row carries a tone + guarded PDF download URL.
	"""
	if not customer:
		return []
	rows = frappe.get_all(
		"Quotation",
		filters={
			"quotation_to": "Customer",
			"party_name": customer,
			"docstatus": ["<", 2],
		},
		fields=[
			"name",
			"transaction_date",
			"valid_till",
			"status",
			"order_type",
			"grand_total",
			"currency",
		],
		order_by="transaction_date desc, creation desc",
		limit=limit,
	)
	for r in rows:
		r["tone"] = quotation_status_tone(r.status)
		r["pdf_url"] = _pdf_url("Quotation", r["name"])
	return rows


def get_customer_invoices(customer: str, limit: int = 200) -> list[dict]:
	"""Submitted Sales Invoices for this customer, newest first.

	Only submitted invoices (docstatus 1) are shown - drafts are internal.
	Each row carries a tone + guarded PDF download URL.
	"""
	if not customer:
		return []
	rows = frappe.get_all(
		"Sales Invoice",
		filters={"customer": customer, "docstatus": 1},
		fields=[
			"name",
			"posting_date",
			"due_date",
			"status",
			"grand_total",
			"outstanding_amount",
			"currency",
		],
		order_by="posting_date desc, creation desc",
		limit=limit,
	)
	for r in rows:
		r["tone"] = invoice_status_tone(r.status)
		r["pdf_url"] = _pdf_url("Sales Invoice", r["name"])
	return rows


def quotation_status_tone(status: str | None) -> str:
	"""CSS tone class for a Quotation status pill."""
	if status in ("Ordered", "Partially Ordered"):
		return "success"
	if status in ("Open", "Replied"):
		return "active"
	if status in ("Lost", "Expired", "Cancelled"):
		return "danger"
	return "muted"


def invoice_status_tone(status: str | None) -> str:
	"""CSS tone class for a Sales Invoice status pill."""
	if status == "Paid":
		return "success"
	if status and "Overdue" in status:
		return "danger"
	if status in ("Unpaid", "Partly Paid", "Submitted", "Unpaid and Discounted", "Partly Paid and Discounted"):
		return "active"
	return "muted"


def _pdf_url(doctype: str, name: str) -> str:
	return (
		"/api/method/cgm_shipping.cgm_worldwide_shipping.customizations.portal.download_transaction_pdf"
		+ f"?doctype={quote(doctype, safe='')}&name={quote(name, safe='')}"
	)


@frappe.whitelist()
def download_transaction_pdf(doctype: str, name: str):
	"""Stream a customer's own Quotation / Sales Invoice as a PDF.

	Portal users hold no desk read perm on these doctypes, so a direct
	print URL would 403. This re-derives the customer from the session,
	confirms the document is addressed to them, then renders and streams
	the PDF. Only Quotation and Sales Invoice are downloadable here.
	"""
	if doctype not in ("Quotation", "Sales Invoice"):
		raise frappe.PermissionError(_("This document type can't be downloaded here."))

	customer = customer_for_user(frappe.session.user)
	if not customer:
		raise frappe.PermissionError(_("No customer is linked to your account."))

	if doctype == "Sales Invoice":
		owner = frappe.db.get_value("Sales Invoice", name, "customer")
	else:
		row = frappe.db.get_value(
			"Quotation", name, ["quotation_to", "party_name"], as_dict=True
		)
		owner = row.party_name if (row and row.quotation_to == "Customer") else None

	if not owner or owner != customer:
		raise frappe.PermissionError(_("You can only download your own documents."))

	pdf = frappe.get_print(doctype, name, as_pdf=True)
	frappe.local.response.filename = f"{name}.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "download"


# ─── Documents ───────────────────────────────────────────────────────────────


def get_shipment_documents(project_name: str) -> list[dict]:
	"""Vetted documents on a shipment that a customer may download.

	Only rows that (a) have an attachment and (b) have been verified by
	staff (`verified_on` set) are surfaced - the customer never sees
	draft, missing, or unverified paperwork. Each row is enriched with a
	friendly document name and a guarded download URL.
	"""
	if not project_name:
		return []
	rows = frappe.get_all(
		"Shipment Document",
		filters={
			"parent": project_name,
			"parenttype": "Project",
			"attachment": ["is", "set"],
			"verified_on": ["is", "set"],
		},
		fields=[
			"name",
			"document_type",
			"attachment",
			"verified_on",
			"uploaded_on",
			"remarks",
		],
		order_by="verified_on desc",
	)
	for row in rows:
		row["doc_label"] = _document_label(row.get("document_type"))
		row["download_url"] = (
			"/api/method/cgm_shipping.cgm_worldwide_shipping.customizations.portal.download_shipment_document"
			+ f"?project={quote(project_name, safe='')}"
			+ f"&row={quote(row['name'], safe='')}"
		)
	return rows


def get_all_customer_documents(customer: str, limit: int = 500) -> list[dict]:
	"""Every vetted, downloadable document across a customer's shipments.

	One join over Shipment Document → Project keeps this to a single query
	instead of one per shipment. Same vetting rule as
	`get_shipment_documents`: attachment present and verified by staff.
	Each row carries its owning shipment's ref + a guarded download URL.
	"""
	if not customer:
		return []
	rows = frappe.db.sql(
		"""
		SELECT sd.name, sd.document_type, sd.attachment, sd.verified_on,
		       sd.remarks, p.name AS project, p.custom_cgm_ref_no AS ref
		FROM `tabShipment Document` sd
		JOIN `tabProject` p ON p.name = sd.parent
		WHERE sd.parenttype = 'Project'
		  AND p.customer = %s
		  AND IFNULL(sd.attachment, '') != ''
		  AND sd.verified_on IS NOT NULL
		ORDER BY sd.verified_on DESC
		LIMIT %s
		""",
		(customer, limit),
		as_dict=True,
	)
	for row in rows:
		row["doc_label"] = _document_label(row.get("document_type"))
		row["ref"] = row.get("ref") or row.get("project")
		row["shipment_url"] = "/shipment?name=" + quote(row["project"], safe="")
		row["download_url"] = (
			"/api/method/cgm_shipping.cgm_worldwide_shipping.customizations.portal.download_shipment_document"
			+ f"?project={quote(row['project'], safe='')}"
			+ f"&row={quote(row['name'], safe='')}"
		)
	return rows


def _document_label(document_type: str | None) -> str:
	"""Friendly label for a Document Type (its 'Full Name'/code, else id)."""
	if not document_type:
		return _("Document")
	return frappe.db.get_value("Document Type", document_type, "code") or document_type


@frappe.whitelist()
def download_shipment_document(project: str, row: str):
	"""Stream a shipment document attachment to its owning customer.

	Shipment-document attachments are private Files; a Website User has no
	desk permission on them, so a direct `/private/files/...` hit would
	403. This endpoint re-derives the customer from the session, verifies
	the project belongs to them, confirms `row` is a Shipment Document on
	that project, and only then streams the file. The customer never sees
	a raw file path and can't enumerate other customers' documents.
	"""
	customer = customer_for_user(frappe.session.user)
	if not customer:
		raise frappe.PermissionError(_("No customer is linked to your account."))

	owner = frappe.db.get_value("Project", project, "customer")
	if not owner or owner != customer:
		raise frappe.PermissionError(_("You can only download your own shipment documents."))

	file_url = frappe.db.get_value(
		"Shipment Document",
		{"name": row, "parent": project, "parenttype": "Project"},
		"attachment",
	)
	if not file_url:
		raise frappe.PermissionError(_("Document not found on this shipment."))

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	frappe.local.response.filename = file_doc.file_name or "document"
	frappe.local.response.filecontent = file_doc.get_content()
	frappe.local.response.type = "download"
