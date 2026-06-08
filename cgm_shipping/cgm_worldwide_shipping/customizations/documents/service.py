"""Shipment and task document sync — domain logic (not generic utilities)."""
from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY

SHIPMENT_DOCUMENTS_FIELD = "custom_shipment_documents"
TASK_DOCUMENTS_FIELD = "custom_task_documents"

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
}

CUSTOMER_ATTACH_TO_DOCUMENT_CODE = {
	"custom_kra_pin_attachment": "KRA_PIN",
}


def get_project_documents_fieldname():
	project_fields = frappe.get_meta("Project")
	if project_fields.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return SHIPMENT_DOCUMENTS_FIELD
	return None


def ensure_project_shipment_documents_field():
	if get_project_documents_fieldname():
		return SHIPMENT_DOCUMENTS_FIELD

	fieldname = SHIPMENT_DOCUMENTS_FIELD
	cf_name = f"Project-{fieldname}"

	if frappe.db.exists("Custom Field", cf_name):
		frappe.clear_cache(doctype="Project")
		return fieldname

	project_fields = frappe.get_meta("Project")
	insert_after = "custom_shipment_status"
	if not project_fields.has_field(insert_after):
		insert_after = "custom_shipment_type"
	if not project_fields.has_field(insert_after):
		insert_after = "customer"

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


def get_preshipment_attachments(source_doc):
	attachments = {"CI": None, "PKL": None}
	source_fields = source_doc.meta
	for code in ("CI", "PKL"):
		fieldname = f"custom_{code.lower()}_attachment"
		if source_fields.has_field(fieldname):
			attachments[code] = source_doc.get(fieldname)

	if attachments["CI"] and attachments["PKL"]:
		return attachments

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
	if not existing_type or not incoming_type:
		return False
	if existing_type == incoming_type:
		return True
	existing_code = frappe.db.get_value("Document Type", existing_type, "code")
	incoming_code = frappe.db.get_value("Document Type", incoming_type, "code")
	return bool(existing_code and incoming_code and existing_code == incoming_code)


def get_document_type_link_name(code):
	if not code:
		return None
	name = frappe.db.get_value("Document Type", {"code": code}, "name")
	if name:
		return name
	if frappe.db.exists("Document Type", code):
		return code
	return None


def append_verified_doc_row(project_doc, document_type, attachment_url):
	if not attachment_url or not document_type:
		return
	if not frappe.db.exists("Document Type", document_type):
		return
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return

	rows = project_doc.get(SHIPMENT_DOCUMENTS_FIELD) or []
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


def ensure_document_types():
	for code, defaults in DOCUMENT_TYPE_DEFAULTS.items():
		if get_document_type_link_name(code):
			continue
		doc = frappe.new_doc("Document Type")
		doc.code = code
		for key, value in defaults.items():
			setattr(doc, key, value)
		doc.insert(ignore_permissions=True)
		if doc.meta.is_submittable and doc.docstatus == 0:
			doc.submit()


def carry_preshipment_docs_to_project(project_doc, source_doc):
	ensure_document_types()
	attachments = get_preshipment_attachments(source_doc)
	for code in ("CI", "PKL"):
		attachment_url = attachments.get(code)
		if not attachment_url:
			continue
		document_type = get_document_type_link_name(code)
		if document_type:
			append_verified_doc_row(project_doc, document_type, attachment_url)


def carry_customer_attachments_to_project(project_doc, customer_ref):
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


def carry_project_shipment_documents_to_sea_tasks(project_name, task_sequences=None):
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.service import (
		is_auto_complete_task,
	)

	if not project_name or not frappe.db.exists("Project", project_name):
		return []
	if not frappe.get_meta("Task").has_field(TASK_DOCUMENTS_FIELD):
		return []

	if task_sequences is None:
		task_sequences = sorted(seq for seq in range(1, 25) if is_auto_complete_task(seq))

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
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return

	ensure_document_types()

	lead_name = project_doc.get("custom_source_lead")
	if not lead_name and project_doc.get("customer"):
		lead_name = frappe.db.get_value("Customer", project_doc.customer, "lead_name")
	if lead_name and frappe.db.exists("Lead", lead_name):
		carry_preshipment_docs_to_project(project_doc, frappe.get_doc("Lead", lead_name))

	opp_name = project_doc.get("custom_source_opportunity")
	if opp_name and frappe.db.exists("Opportunity", opp_name):
		carry_preshipment_docs_to_project(project_doc, frappe.get_doc("Opportunity", opp_name))

	if project_doc.get("customer"):
		carry_customer_attachments_to_project(project_doc, project_doc.customer)

	if project_doc.name:
		carry_task_documents_to_project(project_doc)


def refresh_project_shipment_documents(project_name):
	if not project_name or not frappe.db.exists("Project", project_name):
		return
	if frappe.flags.cgm_syncing_shipment_documents:
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import normalize_shipment_fields_on_doc

	frappe.flags.cgm_syncing_shipment_documents = True
	try:
		project = frappe.get_doc("Project", project_name)
		normalize_shipment_fields_on_doc(project)
		sync_linked_attachments_to_project(project)
		project.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_shipment_documents = False


def refresh_projects_for_customer(customer):
	if not customer:
		return
	for project_name in frappe.get_all("Project", filters={"customer": customer}, pluck="name"):
		refresh_project_shipment_documents(project_name)


@frappe.whitelist()
def sync_project_shipment_documents(project):
	frappe.has_permission("Project", ptype="write", throw=True)
	refresh_project_shipment_documents(project)
	return project
