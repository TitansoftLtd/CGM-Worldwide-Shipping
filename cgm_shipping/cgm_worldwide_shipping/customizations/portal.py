# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Shared data layer for the CGM customer portal.

The portal lets a customer (consignee) track their own shipments. A
shipment is a `Project`; granular tracking lives on `Container Tracker`
rows linked to the project, and the customer-vetted paperwork lives on
the project's `custom_documents` child table (Shipment Document).

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
from frappe.utils import cint

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
# page, dashboard and detail header stay consistent. Some sites still have
# CGM Ref No is company-entered; Project Reference / project_name are auto.
# Prefer CGM Ref when set. Filter through Project meta so get_all never
# selects a missing column.
_SHIPMENT_LIST_FIELD_CANDIDATES = [
	"name",
	"project_name",
	"custom_project_reference",
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


def shipment_list_fields() -> list[str]:
	meta = frappe.get_meta("Project")
	return [
		field
		for field in _SHIPMENT_LIST_FIELD_CANDIDATES
		if field == "name" or meta.has_field(field)
	]


def _project_ref_sql_coalesce(alias: str = "p") -> str:
	meta = frappe.get_meta("Project")
	parts = []
	if meta.has_field("custom_cgm_ref_no"):
		parts.append(f"NULLIF({alias}.custom_cgm_ref_no, '')")
	if meta.has_field("custom_project_reference"):
		parts.append(f"NULLIF({alias}.custom_project_reference, '')")
	parts.extend([f"NULLIF({alias}.project_name, '')", f"{alias}.name"])
	return "COALESCE(" + ", ".join(parts) + ")"


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
		fields=shipment_list_fields(),
		order_by="modified desc",
		limit=limit,
	)


def shipment_display_ref(row: dict) -> str:
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
		display_ref_from_values,
	)

	return display_ref_from_values(row)


def get_shipment_for_customer(project_name: str, customer: str) -> dict | None:
	"""Fetch a single shipment, enforcing customer ownership.

	Returns None when the project doesn't exist or belongs to another
	customer - callers render a "not authorized" state rather than leaking
	existence.
	"""
	if not project_name or not customer:
		return None
	detail_fields = [
		"name",
		"project_name",
		"custom_project_reference",
		"custom_cgm_ref_no",
		"customer",
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
		# Route / carrier / document fields added to Project.
		"custom_etd",
		"custom_expected_time_of_depatureetd",
		"custom_country_of_origin",
		"custom_final_destination",
		"custom_destination_country",
		"custom_vessel",
		"custom_airline",
		"custom_shipping_line",
		"custom_bill_of_lading",
		"custom_air_waybill",
		"custom_description_of_goods",
		# Pass-through charges billed on the shipment.
		"custom_breakbulk_charges",
		"custom_handling_charges",
		"custom_kebs_charges",
		"modified",
	]
	meta = frappe.get_meta("Project")
	fields = [f for f in detail_fields if f == "name" or meta.has_field(f)]
	row = frappe.db.get_value(
		"Project",
		project_name,
		fields,
		as_dict=True,
	)
	if not row or row.customer != customer:
		return None
	row["ref"] = shipment_display_ref(row)
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
		r["pdf_view_url"] = _pdf_url("Quotation", r["name"], "inline")
		r["pdf_download_url"] = _pdf_url("Quotation", r["name"], "attachment")
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
		r["pdf_view_url"] = _pdf_url("Sales Invoice", r["name"], "inline")
		r["pdf_download_url"] = _pdf_url("Sales Invoice", r["name"], "attachment")
	return rows


def document_status_tone(status: str | None) -> str:
	"""CSS tone class for a Shipment Document status pill (matches Desk grid)."""
	if not status or status == "Missing":
		return "muted"
	if status == "Uploaded":
		return "info"
	if status == "Verified":
		return "success"
	if status == "Rejected":
		return "danger"
	return "muted"


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


def _pdf_url(doctype: str, name: str, disposition: str = "attachment") -> str:
	return (
		"/api/method/cgm_shipping.cgm_worldwide_shipping.customizations.portal.download_transaction_pdf"
		+ f"?doctype={quote(doctype, safe='')}&name={quote(name, safe='')}"
		+ f"&disposition={disposition}"
	)


@frappe.whitelist()
def download_transaction_pdf(doctype: str, name: str, disposition: str = "attachment"):
	"""Stream a customer's own Quotation / Sales Invoice as a PDF.

	Portal users hold no desk read perm on these doctypes, so a direct
	print URL would 403. This re-derives the customer from the session,
	confirms the document is addressed to them, then renders and streams
	the PDF. Only Quotation and Sales Invoice are served here.

	``disposition`` controls how the browser handles it:
	  - "inline"     → preview in a new tab (Content-Disposition: inline)
	  - "attachment" → force a download (the default)
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
		raise frappe.PermissionError(_("You can only access your own documents."))

	pdf = frappe.get_print(doctype, name, as_pdf=True)
	frappe.local.response.filename = f"{name}.pdf"
	frappe.local.response.filecontent = pdf
	# "pdf" → inline preview; "download" → save-as. Frappe's response
	# builder maps these to the right Content-Disposition header.
	frappe.local.response.type = "pdf" if disposition == "inline" else "download"


# ─── Documents ───────────────────────────────────────────────────────────────


def _portal_document_fields() -> list[str]:
	fields = [
		"name",
		"document_type",
		"attachment",
		"verified_on",
		"remarks",
		"status",
	]
	meta = frappe.get_meta("Shipment Document")
	for fieldname in (
		"draft_documents",
		"final_attachment",
		"draft_documents_uploaded_on",
		"final_document_uploaded_on",
		"uploaded_on",
	):
		if meta.has_field(fieldname):
			fields.append(fieldname)
	return fields


def _is_portal_visible_document(row: dict) -> bool:
	"""Portal document rows; hide rejected rows and download-restricted types."""
	status = (row.get("status") or "Missing").strip()
	if status == "Rejected":
		return False
	document_type = row.get("document_type")
	if document_type and not _user_can_download_document_type(document_type):
		return False
	return True


def _user_can_download_document_type(document_type: str | None) -> bool:
	"""True when Document Type has no download gate, or the user has an allowed role."""
	if not document_type or not frappe.db.exists("Document Type", document_type):
		return True
	if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles():
		return True
	meta = frappe.get_meta("Document Type")
	if not meta.has_field("requires_download_permission"):
		return True
	requires = cint(
		frappe.db.get_value("Document Type", document_type, "requires_download_permission")
	)
	if not requires:
		return True
	if not meta.has_field("download_roles"):
		return False
	allowed = frappe.get_all(
		"CGM Role Item",
		filters={
			"parent": document_type,
			"parenttype": "Document Type",
			"parentfield": "download_roles",
		},
		pluck="role",
	)
	if not allowed:
		return False
	user_roles = set(frappe.get_roles())
	return bool(user_roles.intersection(allowed))


_PORTAL_INTERNAL_REMARKS = frozenset(
	{"Carried from Project (approved on Lead/Opportunity/Customer)"}
)
_PORTAL_INTERNAL_REMARK_PREFIXES = (
	"From submitted Bill of Lading",
)


def _portal_document_remarks(remarks: str | None) -> str:
	"""Drop internal sync notes before rendering on the customer portal."""
	if not remarks:
		return ""
	trimmed = remarks.strip()
	if trimmed in _PORTAL_INTERNAL_REMARKS:
		return ""
	if any(trimmed.startswith(prefix) for prefix in _PORTAL_INTERNAL_REMARK_PREFIXES):
		return ""
	return trimmed


def _enrich_portal_document(row: dict, project_name: str) -> dict:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		primary_attachment,
	)

	row["attachment"] = primary_attachment(row)
	row["uploaded_on"] = (
		row.get("final_document_uploaded_on")
		or row.get("draft_documents_uploaded_on")
		or row.get("uploaded_on")
	)
	row["remarks"] = _portal_document_remarks(row.get("remarks"))
	row["doc_label"] = _document_label(row.get("document_type"))
	status = (row.get("status") or "Missing").strip()
	row["status"] = status
	row["tone"] = document_status_tone(status)
	return row


def get_shipment_documents(project_name: str) -> list[dict]:
	"""Documents on a shipment with status for the customer portal.

	Surfaces every Shipment Document row except Rejected, matching the
	Project child table. Each row carries a friendly document name and
	status badge tone.
	"""
	if not project_name:
		return []
	rows = frappe.get_all(
		"Shipment Document",
		filters={
			"parent": project_name,
			"parenttype": "Project",
			"status": ["!=", "Rejected"],
		},
		fields=_portal_document_fields(),
		order_by="document_type asc, modified desc",
	)
	visible = []
	for row in rows:
		if not _is_portal_visible_document(row):
			continue
		visible.append(_enrich_portal_document(row, project_name))
	return visible


def get_all_customer_documents(customer: str, limit: int = 500) -> list[dict]:
	"""Every Shipment Document across a customer's shipments (portal list).

	One join over Shipment Document → Project keeps this to a single query.
	Same visibility rule as `get_shipment_documents`. Each row carries its
	owning shipment ref and document status.
	"""
	if not customer:
		return []
	ref_sql = _project_ref_sql_coalesce("p")
	ref_sql = _project_ref_sql_coalesce("p")
	meta = frappe.get_meta("Shipment Document")
	extra_cols = []
	for fieldname in ("draft_documents", "final_attachment"):
		if meta.has_field(fieldname):
			extra_cols.append(f"sd.{fieldname}")
	uploaded_parts = [
		f"sd.{fieldname}"
		for fieldname in (
			"final_document_uploaded_on",
			"draft_documents_uploaded_on",
			"uploaded_on",
		)
		if meta.has_field(fieldname)
	]
	uploaded_select = (
		f"COALESCE({', '.join(uploaded_parts)}) AS uploaded_on"
		if uploaded_parts
		else "NULL AS uploaded_on"
	)
	rows = frappe.db.sql(
		f"""
		SELECT sd.name, sd.document_type, sd.attachment, sd.verified_on,
		       {uploaded_select}, sd.status, sd.remarks, p.name AS project,
		       {ref_sql} AS ref
		       {", " + ", ".join(extra_cols) if extra_cols else ""}
		FROM `tabShipment Document` sd
		JOIN `tabProject` p ON p.name = sd.parent
		WHERE sd.parenttype = 'Project'
		  AND p.customer = %s
		  AND IFNULL(sd.status, 'Missing') != 'Rejected'
		ORDER BY p.modified DESC, sd.document_type ASC, sd.modified DESC
		LIMIT %s
		""",
		(customer, limit),
		as_dict=True,
	)
	out = []
	for row in rows:
		if not _is_portal_visible_document(row):
			continue
		_enrich_portal_document(row, row["project"])
		row["ref"] = row.get("ref") or row.get("project")
		row["shipment_url"] = "/shipment?name=" + quote(row["project"], safe="")
		out.append(row)
	return out


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

	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		primary_attachment,
	)

	fields = _portal_document_fields()
	doc_row = frappe.db.get_value(
		"Shipment Document",
		{"name": row, "parent": project, "parenttype": "Project"},
		fields,
		as_dict=True,
	)
	if not doc_row or not _is_portal_visible_document(doc_row):
		raise frappe.PermissionError(_("Document not found on this shipment."))

	if not _user_can_download_document_type(doc_row.get("document_type")):
		raise frappe.PermissionError(_("You are not allowed to download this document type."))

	file_url = primary_attachment(doc_row)
	if not file_url:
		raise frappe.PermissionError(_("Document not found on this shipment."))

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	frappe.local.response.filename = file_doc.file_name or "document"
	frappe.local.response.filecontent = file_doc.get_content()
	frappe.local.response.type = "download"


# ─── Permits ─────────────────────────────────────────────────────────────────


def get_shipment_permits(project_name: str) -> list[dict]:
	"""Regulatory permit certificates on a shipment that a customer may download.

	Only rows with a `permit_document` attachment are surfaced - payment
	invoices and receipts stay internal. Each row is enriched with a friendly
	permit label and a guarded download URL.
	"""
	if not project_name:
		return []
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import PERMIT_REGISTER_FIELD

	if not frappe.get_meta("Project").has_field(PERMIT_REGISTER_FIELD):
		return []

	rows = frappe.get_all(
		"Permit Register",
		filters={
			"parent": project_name,
			"parenttype": "Project",
			"parentfield": PERMIT_REGISTER_FIELD,
			"permit_document": ["is", "set"],
		},
		fields=[
			"name",
			"permit_type",
			"permit_document",
			"status",
			"stage",
			"approval_date",
			"issuing_body",
		],
		order_by="approval_date desc, modified desc",
	)
	for row in rows:
		row["permit_label"] = _permit_label(row.get("permit_type"))
		row["download_url"] = (
			"/api/method/cgm_shipping.cgm_worldwide_shipping.customizations.portal.download_shipment_permit"
			+ f"?project={quote(project_name, safe='')}"
			+ f"&row={quote(row['name'], safe='')}"
		)
	return rows


def _permit_label(permit_type: str | None) -> str:
	"""Friendly label for a Permit Type (permit_name, else id)."""
	if not permit_type:
		return _("Permit")
	return frappe.db.get_value("Permit Type", permit_type, "permit_name") or permit_type


@frappe.whitelist()
def download_shipment_permit(project: str, row: str):
	"""Stream a permit certificate attachment to its owning customer."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import PERMIT_REGISTER_FIELD

	customer = customer_for_user(frappe.session.user)
	if not customer:
		raise frappe.PermissionError(_("No customer is linked to your account."))

	owner = frappe.db.get_value("Project", project, "customer")
	if not owner or owner != customer:
		raise frappe.PermissionError(_("You can only download your own shipment permits."))

	file_url = frappe.db.get_value(
		"Permit Register",
		{
			"name": row,
			"parent": project,
			"parenttype": "Project",
			"parentfield": PERMIT_REGISTER_FIELD,
		},
		"permit_document",
	)
	if not file_url:
		raise frappe.PermissionError(_("Permit not found on this shipment."))

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	frappe.local.response.filename = file_doc.file_name or "permit"
	frappe.local.response.filecontent = file_doc.get_content()
	frappe.local.response.type = "download"


@frappe.whitelist()
def post_shipment_update(project: str, subject: str, message: str) -> dict:
	"""Customer portal: post an operational Update (source=Customer) for a shipment."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates import (
		post_customer_update,
	)

	customer = customer_for_user(frappe.session.user)
	if not customer:
		raise frappe.PermissionError(_("No customer is linked to your account."))

	shipment = get_shipment_for_customer(project, customer)
	if not shipment:
		raise frappe.PermissionError(_("You can only post updates on your own shipments."))

	return post_customer_update(
		project,
		subject,
		message,
		customer=customer,
	)


@frappe.whitelist()
def get_shipment_updates_portal(project: str) -> list[dict]:
	"""Customer portal: updates posted by the logged-in user for a shipment."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates import (
		get_my_updates_for_project,
	)

	customer = customer_for_user(frappe.session.user)
	if not customer:
		raise frappe.PermissionError(_("No customer is linked to your account."))

	shipment = get_shipment_for_customer(project, customer)
	if not shipment:
		raise frappe.PermissionError(_("You can only view updates on your own shipments."))

	return get_my_updates_for_project(project, limit=100)
