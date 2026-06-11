"""Document extraction, synchronization, and validation for shipment files."""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CUSTOMER_ATTACH_TO_DOCUMENT_CODE,
	OPPORTUNITY_DOCUMENTS_FIELD,
	SHIPMENT_DOCUMENTS_FIELD,
	TASK_DOCUMENTS_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import get_field_from_meta



def get_project_documents_fieldname():
	"""Return the Project child-table fieldname for shipment documents, or None if absent."""
	project_fields = frappe.get_meta("Project")
	if project_fields.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return SHIPMENT_DOCUMENTS_FIELD
	return None


def ensure_project_documents_field():
	"""Create the Shipment Documents table on Project when it is missing."""
	# 1. Return early when the field already exists.
	if get_project_documents_fieldname():
		return SHIPMENT_DOCUMENTS_FIELD

	fieldname = SHIPMENT_DOCUMENTS_FIELD
	cf_name = f"Project-{fieldname}"

	# 2. Reload cache and return when the Custom Field record already exists.
	if frappe.db.exists("Custom Field", cf_name):
		frappe.clear_cache(doctype="Project")
		return fieldname

	# 3. Choose the best anchor field for insert_after.
	project_fields = frappe.get_meta("Project")
	insert_after = "custom_shipment_status"
	if not project_fields.has_field(insert_after):
		insert_after = "custom_shipment_type"
	if not project_fields.has_field(insert_after):
		insert_after = "customer"

	# 4. Create and insert the Custom Field.
	doc = frappe.new_doc("Custom Field")
	doc.update(
		{
			"dt": "Project",
			"fieldname": fieldname,
			"label": "Shipment Documents",
			"fieldtype": "Table",
			"options": "Shipment Document",
			"insert_after": insert_after,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Project")
	return fieldname


# ─── Pre-shipment Attachment Helpers ─────────────────────────────────────────


def get_preshipment_attachments(source_doc):
	# 1. Read explicit CI/PKL attachment fields when available.
	attachments = {"CI": None, "PKL": None}
	source_fields = source_doc.meta
	for code in ("CI", "PKL"):
		fieldname = f"custom_{code.lower()}_attachment"
		if source_fields.has_field(fieldname):
			attachments[code] = source_doc.get(fieldname)

	# 2. Return early when both attachments were resolved from fields.
	if attachments["CI"] and attachments["PKL"]:
		return attachments

	# 3. Fall back to timeline file attachments for older records.
	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": source_doc.doctype,
			"attached_to_name": source_doc.name,
			"is_folder": 0,
		},
		fields=["file_name", "file_url"],
		order_by="creation desc",
	)

	for file_row in files:
		filename = (file_row.file_name or "").lower()
		if not attachments["CI"] and (
			"commercial invoice" in filename
			or filename.startswith("ci")
			or "_ci" in filename
			or "-ci" in filename
		):
			attachments["CI"] = file_row.file_url
		if not attachments["PKL"] and (
			"packing list" in filename
			or filename.startswith("pkl")
			or "_pkl" in filename
			or "-pkl" in filename
		):
			attachments["PKL"] = file_row.file_url
		if attachments["CI"] and attachments["PKL"]:
			break

	return attachments


def document_types_match(existing_type, incoming_type):
	"""Match Document Type rows by link name or shared code (e.g. CI vs Commercial Invoice)."""
	if not existing_type or not incoming_type:
		return False
	if existing_type == incoming_type:
		return True
	existing_code = frappe.db.get_value("Document Type", existing_type, "code")
	incoming_code = frappe.db.get_value("Document Type", incoming_type, "code")
	return bool(existing_code and incoming_code and existing_code == incoming_code)


def append_verified_doc_row(project_doc, document_type, attachment_url):
	# 1. Skip when any required value is absent.
	if not attachment_url or not document_type:
		return
	if not frappe.db.exists("Document Type", document_type):
		return
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return

	rows = project_doc.get(SHIPMENT_DOCUMENTS_FIELD) or []

	# 2. Update the existing row when the document type is already present.
	for row in rows:
		if document_types_match(row.document_type, document_type):
			if not row.attachment:
				row.attachment = attachment_url
			row.status = "Verified"
			if not row.uploaded_by:
				row.uploaded_by = frappe.session.user
			if not row.uploaded_on:
				row.uploaded_on = now_datetime()
			if not row.verified_by:
				row.verified_by = frappe.session.user
			if not row.verified_on:
				row.verified_on = now_datetime()
			return

	# 3. Append a new verified row when no existing row matched.
	project_doc.append(
		SHIPMENT_DOCUMENTS_FIELD,
		{
			"document_type": document_type,
			"attachment": attachment_url,
			"required": 1,
			"status": "Verified",
			"uploaded_by": frappe.session.user,
			"uploaded_on": now_datetime(),
			"verified_by": frappe.session.user,
			"verified_on": now_datetime(),
		},
	)


DOCUMENT_TYPE_DEFAULTS = {
	"CI": {
		"category": "Commercial",
		"default_required": 1,
		"required_stage": "Pre-IDF",
	},
	"PKL": {
		"category": "Commercial",
		"default_required": 1,
		"required_stage": "Pre-IDF",
	},
	"KRA_PIN": {
		"category": "Compliance",
		"default_required": 1,
		"required_stage": "Pre-IDF",
	},
	"BL": {
		"category": "Transport",
		"default_required": 0,
		"required_stage": "Pre-IDF",
	},
	"AWB": {
		"category": "Transport",
		"default_required": 0,
		"required_stage": "Arrival & manifest",
	},
}

# Customer Attach field → Document Type code.
CUSTOMER_ATTACH_TO_DOCUMENT_CODE = {
	"custom_kra_pin_attachment": "KRA_PIN",
}


def ensure_document_types():
	"""Ensure Document Type master rows exist for synced shipment files."""
	for code, defaults in DOCUMENT_TYPE_DEFAULTS.items():
		if get_document_type_link_name(code):
			continue

		# 1. Create and submit the Document Type when it does not yet exist.
		doc = frappe.new_doc("Document Type")
		doc.code = code
		for key, value in defaults.items():
			setattr(doc, key, value)
		doc.insert(ignore_permissions=True)
		if doc.meta.is_submittable and doc.docstatus == 0:
			doc.submit()


def carry_preshipment_docs_to_project(project_doc, source_doc):
	"""Copy CI and PKL attachments from a Lead/Opportunity into Project shipment document rows."""
	ensure_document_types()
	attachments = get_preshipment_attachments(source_doc)
	for code in ("CI", "PKL"):
		attachment_url = attachments.get(code)
		if not attachment_url:
			continue
		document_type = get_document_type_link_name(code)
		if document_type:
			append_verified_doc_row(project_doc, document_type, attachment_url)


def carry_clients_documents_to_project(project_doc, source_doc) -> None:
	"""Copy all Clients Documents rows from Opportunity onto Project shipment documents."""
	if not source_doc or not source_doc.meta.has_field(OPPORTUNITY_DOCUMENTS_FIELD):
		return
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return

	ensure_document_types()
	for row in source_doc.get(OPPORTUNITY_DOCUMENTS_FIELD) or []:
		if not row.document_type or not row.attachment:
			continue
		if not frappe.db.exists("Document Type", row.document_type):
			continue
		_append_or_update_shipment_document_row(project_doc, row)


def _append_or_update_shipment_document_row(project_doc, source_row) -> None:
	rows = project_doc.get(SHIPMENT_DOCUMENTS_FIELD) or []
	for existing in rows:
		if not document_types_match(existing.document_type, source_row.document_type):
			continue
		if not existing.attachment:
			existing.attachment = source_row.attachment
		if source_row.status and source_row.status != "Missing":
			existing.status = source_row.status
		for field in (
			"uploaded_by",
			"uploaded_on",
			"verified_by",
			"verified_on",
			"remarks",
		):
			value = source_row.get(field)
			if value and not existing.get(field):
				existing.set(field, value)
		return

	project_doc.append(
		SHIPMENT_DOCUMENTS_FIELD,
		{
			"document_type": source_row.document_type,
			"attachment": source_row.attachment,
			"status": source_row.status or "Uploaded",
			"uploaded_by": source_row.uploaded_by,
			"uploaded_on": source_row.uploaded_on,
			"verified_by": source_row.verified_by,
			"verified_on": source_row.verified_on,
			"remarks": source_row.remarks,
		},
	)


def get_bill_of_lading_attachment_url(
	bl_name: str | None = None, source_doc=None
) -> str | None:
	"""Resolve BL file URL from the Bill of Lading record or source Clients Documents."""
	if bl_name and frappe.db.exists("Bill of Lading", bl_name):
		attachment_url = frappe.db.get_value("Bill of Lading", bl_name, "bill_of_lading")
		if attachment_url:
			return attachment_url

	if not source_doc:
		return None

	clients_field = OPPORTUNITY_DOCUMENTS_FIELD
	if not source_doc.meta.has_field(clients_field):
		return None

	bl_type = get_document_type_link_name("BL")
	if not bl_type:
		return None

	for row in source_doc.get(clients_field) or []:
		if document_types_match(row.document_type, bl_type) and row.attachment:
			return row.attachment
	return None


def carry_bill_of_lading_attachment_to_project(
	project_doc, bl_name: str | None = None, source_doc=None
) -> None:
	"""Add the Bill of Lading file to Project shipment documents (type BL)."""
	ensure_document_types()
	bl_name = bl_name or project_doc.get("custom_bill_of_lading")
	attachment_url = get_bill_of_lading_attachment_url(bl_name, source_doc)
	if not attachment_url:
		return

	document_type = get_document_type_link_name("BL")
	if document_type:
		append_verified_doc_row(project_doc, document_type, attachment_url)


def carry_customer_attachments_to_project(project_doc, customer_ref):
	"""Copy Customer attach fields (e.g. KRA PIN) into Project shipment document rows."""
	if not customer_ref:
		return
	if getattr(customer_ref, "doctype", None) == "Customer":
		customer_doc = customer_ref
	else:
		if not frappe.db.exists("Customer", customer_ref):
			return
		customer_doc = frappe.get_doc("Customer", customer_ref)

	customer_fields = frappe.get_meta("Customer")
	for fieldname, code in CUSTOMER_ATTACH_TO_DOCUMENT_CODE.items():
		if not customer_fields.has_field(fieldname):
			continue
		attachment_url = customer_doc.get(fieldname)
		if not attachment_url:
			continue
		document_type = get_document_type_link_name(code)
		if document_type:
			append_verified_doc_row(project_doc, document_type, attachment_url)


def append_task_document_row(task_doc, document_type, attachment_url, status=None, remarks=None):
	"""Append or update a Shipment Document row on a Task."""
	if not attachment_url or not document_type:
		return
	if not task_doc.meta.has_field(TASK_DOCUMENTS_FIELD):
		return
	if not frappe.db.exists("Document Type", document_type):
		return

	status = status or "Verified"
	for row in task_doc.get(TASK_DOCUMENTS_FIELD) or []:
		if document_types_match(row.document_type, document_type):
			row.attachment = attachment_url
			row.status = status
			if remarks:
				row.remarks = remarks
			if status == "Verified":
				row.verified_by = row.verified_by or frappe.session.user
				row.verified_on = row.verified_on or now_datetime()
			row.uploaded_by = row.uploaded_by or frappe.session.user
			row.uploaded_on = row.uploaded_on or now_datetime()
			return

	task_doc.append(
		TASK_DOCUMENTS_FIELD,
		{
			"document_type": document_type,
			"attachment": attachment_url,
			"status": status,
			"remarks": remarks or "Carried from Project (approved on Lead/Opportunity/Customer)",
			"uploaded_by": frappe.session.user,
			"uploaded_on": now_datetime(),
			"verified_by": frappe.session.user if status == "Verified" else None,
			"verified_on": now_datetime() if status == "Verified" else None,
		},
	)


def carry_project_documents_to_sea_tasks(project_name, task_sequences=None):
	"""
	Copy Project shipment document rows onto sea clearance tasks (audit trail on Task 1–2).
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		SEA_TASK_FLOW_KEY,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		auto_complete_sequences,
	)

	if not project_name or not frappe.db.exists("Project", project_name):
		return []
	if not frappe.get_meta("Task").has_field(TASK_DOCUMENTS_FIELD):
		return []

	task_sequences = task_sequences or sorted(auto_complete_sequences())
	project = frappe.get_doc("Project", project_name)
	source_rows = [
		r
		for r in project.get(SHIPMENT_DOCUMENTS_FIELD) or []
		if r.document_type and r.attachment
	]
	if not source_rows:
		return []

	updated_tasks = []
	for seq in task_sequences:
		task_name = frappe.db.get_value(
			"Task",
			{
				"project": project_name,
				"custom_task_flow_key": SEA_TASK_FLOW_KEY,
				"custom_sequence_no": seq,
			},
			"name",
		)
		if not task_name:
			continue
		task = frappe.get_doc("Task", task_name)
		for row in source_rows:
			append_task_document_row(
				task,
				row.document_type,
				row.attachment,
				status=row.status or "Verified",
				remarks=row.remarks
				or "Carried from Project (approved on Lead/Opportunity/Customer)",
			)
		frappe.flags.cgm_syncing_shipment_documents = True
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_shipment_documents = False
		updated_tasks.append(task_name)
	return updated_tasks


def carry_task_documents_to_project(project_doc, project_name=None):
	"""Copy Task Documents child rows from all tasks on this project."""
	project_name = project_name or project_doc.name
	if not project_name:
		return

	task_fields = frappe.get_meta("Task")
	if not task_fields.has_field("custom_task_documents"):
		return

	for task_name in frappe.get_all("Task", filters={"project": project_name}, pluck="name"):
		task_doc = frappe.get_doc("Task", task_name)
		for row in task_doc.get("custom_task_documents") or []:
			if row.document_type and row.attachment:
				append_verified_doc_row(project_doc, row.document_type, row.attachment)


def sync_linked_attachments_to_project(project_doc):
	"""Pull shipment files from linked Lead, Customer, and Project tasks into custom_shipment_documents."""
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return

	ensure_document_types()

	# 1. Lead (explicit source or via customer).
	lead_name = project_doc.get("custom_source_lead")
	if not lead_name and project_doc.get("customer"):
		lead_name = frappe.db.get_value("Customer", project_doc.customer, "lead_name")
	if lead_name and frappe.db.exists("Lead", lead_name):
		lead_doc = frappe.get_doc("Lead", lead_name)
		carry_preshipment_docs_to_project(project_doc, lead_doc)
		carry_bill_of_lading_attachment_to_project(
			project_doc,
			bl_name=project_doc.get("custom_bill_of_lading") or lead_doc.get("custom_bill_of_lading"),
			source_doc=lead_doc,
		)

	# 2. Opportunity source when present.
	opp_name = project_doc.get("custom_source_opportunity")
	if opp_name and frappe.db.exists("Opportunity", opp_name):
		opp_doc = frappe.get_doc("Opportunity", opp_name)
		carry_clients_documents_to_project(project_doc, opp_doc)
		carry_bill_of_lading_attachment_to_project(
			project_doc,
			bl_name=project_doc.get("custom_bill_of_lading") or opp_doc.get("custom_bill_of_lading"),
			source_doc=opp_doc,
		)

	# 3. Customer attach fields (KRA PIN, etc.).
	if project_doc.get("customer"):
		carry_customer_attachments_to_project(project_doc, project_doc.customer)

	# 4. Task Documents on tasks linked to this project.
	if project_doc.name:
		carry_task_documents_to_project(project_doc)


def refresh_project_documents(project_name):
	"""Re-sync shipment document rows from linked Customer / Tasks and save the Project."""
	if not project_name or not frappe.db.exists("Project", project_name):
		return
	if frappe.flags.cgm_syncing_shipment_documents:
		return

	frappe.flags.cgm_syncing_shipment_documents = True
	try:
		from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
			normalize_shipment_fields_on_doc,
		)

		project = frappe.get_doc("Project", project_name)
		normalize_shipment_fields_on_doc(project)
		sync_linked_attachments_to_project(project)
		project.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_shipment_documents = False


def refresh_projects_for_customer(customer):
	"""Update shipment documents on every Project for this Customer."""
	if not customer:
		return
	for project_name in frappe.get_all("Project", filters={"customer": customer}, pluck="name"):
		refresh_project_documents(project_name)


@frappe.whitelist()
def sync_project_documents(project):
	"""Re-pull Lead / Customer / Task files into Project shipment documents (for support / backfill)."""
	frappe.has_permission("Project", ptype="write", throw=True)
	refresh_project_documents(project)
	return project


def get_document_type_link_name(code):
	"""Resolve the Document Type name for child table links."""
	if not code:
		return None

	# 1. Prefer a match on the code field.
	name = frappe.db.get_value("Document Type", {"code": code}, "name")
	if name:
		return name

	# 2. Fall back to using the code directly as the document name.
	if frappe.db.exists("Document Type", code):
		return code

	return None

@frappe.request_cache
def get_opportunity_documents_field() -> str | None:
	"""Clients Documents table fieldname on Opportunity."""
	return get_field_from_meta("Opportunity", "clients_documents") or next(
		(
			field.fieldname
			for field in frappe.get_meta("Opportunity").fields
			if field.fieldtype == "Table" and "clients_documents" in field.fieldname
		),
		None,
	)


@frappe.request_cache
def get_project_shipment_documents_field() -> str | None:
	"""Shipment Documents table fieldname on Project."""
	if frappe.get_meta("Project").has_field(SHIPMENT_DOCUMENTS_FIELD):
		return SHIPMENT_DOCUMENTS_FIELD
	return get_field_from_meta("Project", "shipment_documents")


# Backward-compatible alias
get_project_documents_field = get_project_shipment_documents_field


# Backward-compatible aliases
refresh_project_shipment_documents = refresh_project_documents
sync_documents = sync_linked_attachments_to_project
