import re

import frappe
from erpnext import get_default_company
from frappe.utils import getdate, now_datetime, today
# CGM reference & shipment-classification helpers were extracted to
# shipment_reference.py; re-exported here so existing
# `from ...customizations.utils import ...` call sites keep working.
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_reference import (  # noqa: E402,F401
	CGM_REF_PATTERN,
	apply_shipment_data,
	assign_cgm_project_reference,
	build_cgm_ref_no,
	cgm_ref_prefix,
	is_cgm_ref,
	normalize_shipment_classification,
	normalize_shipment_fields_on_doc,
)

SEA_TASK_FLOW_KEY = "SEA_IMPORT_E2E"

# Map template labels or old department names -> ERPNext department_name (before company suffix).
DEPARTMENT_NAME_ALIASES = {
	"Administration": "Documentation",
}


def get_sea_task(project: str, seq: int) -> str | None:
	"""Return the name of the sea-clearance Task at `seq` for `project` (or None)."""
	if not project or not seq:
		return None
	return frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": seq,
		},
		"name",
	)


def mark_task_completed(task) -> None:
	"""Write Completed straight to the DB (a nested doc.save can leave list views stale)."""
	frappe.db.set_value(
		"Task",
		task.name,
		{
			"status": "Completed",
			"completed_by": task.completed_by or frappe.session.user,
			"completed_on": task.completed_on or now_datetime(),
			"progress": 100,
		},
		update_modified=True,
	)
	frappe.clear_document_cache("Task", task.name)


# (CGM reference & shipment-classification helpers now live in shipment_reference.py)

SHIPMENT_DOCUMENTS_FIELD = "custom_shipment_documents"
OPPORTUNITY_DOCUMENTS_FIELD = "custom_clients_documents"
TASK_DOCUMENTS_FIELD = "custom_task_documents"


def get_project_documents_fieldname():
	"""Return the Project child-table fieldname for shipment documents, or None if absent."""
	project_fields = frappe.get_meta("Project")
	if project_fields.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return SHIPMENT_DOCUMENTS_FIELD
	return None


def ensure_project_shipment_documents_field():
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


def carry_project_shipment_documents_to_sea_tasks(project_name, task_sequences=None):
	"""
	Copy Project shipment document rows onto sea clearance tasks (audit trail on Task 1–2).
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
		SEA_AUTO_COMPLETE_TASK_SEQS,
		SEA_TASK_FLOW_KEY,
	)

	if not project_name or not frappe.db.exists("Project", project_name):
		return []
	if not frappe.get_meta("Task").has_field(TASK_DOCUMENTS_FIELD):
		return []

	task_sequences = task_sequences or sorted(SEA_AUTO_COMPLETE_TASK_SEQS)
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


def refresh_project_shipment_documents(project_name):
	"""Re-sync shipment document rows from linked Customer / Tasks and save the Project."""
	if not project_name or not frappe.db.exists("Project", project_name):
		return
	if frappe.flags.cgm_syncing_shipment_documents:
		return

	frappe.flags.cgm_syncing_shipment_documents = True
	try:
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
		refresh_project_shipment_documents(project_name)


@frappe.whitelist()
def sync_project_shipment_documents(project):
	"""Re-pull Lead / Customer / Task files into Project shipment documents (for support / backfill)."""
	frappe.has_permission("Project", ptype="write", throw=True)
	refresh_project_shipment_documents(project)
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


# ─── Sea Task Template ────────────────────────────────────────────────────────


def load_sea_task_template():
	"""Return sea import tasks from CGM Shipping Settings."""
	# 1. Load and sort template rows by their index.
	settings = frappe.get_single("CGM Shipping Settings")
	rows = sorted(settings.get("custom_sea_import_task_template") or [], key=lambda r: r.idx or 0)

	# 2. Validate and collect each row.
	out = []
	for row in rows:
		subject = (row.task_subject or "").strip()
		dept = normalize_department_stem(row.department)
		if not subject:
			continue
		if not dept:
			frappe.throw(f"Sea import task template: Department is required for task: {subject}")
		out.append({"subject": subject, "department": dept})

	if not out:
		frappe.throw("Add at least one row to Sea import task template in CGM Shipping Settings.")

	return out


# ─── Department Resolution ────────────────────────────────────────────────────


def get_department_name_stem(raw):
	"""Extract the department name before the company abbreviation suffix."""
	value = (raw or "").strip()
	if not value:
		return ""

	# 1. ERPNext department docnames follow `{department_name} - {abbr}` — strip the suffix.
	if " - " in value:
		return value.split(" - ", 1)[0].strip()
	return value


def normalize_department_stem(raw) -> str:
	"""Template / task stem only (e.g. Finance), never Finance - C from another site."""
	stem = get_department_name_stem(raw)
	if not stem:
		return ""
	return DEPARTMENT_NAME_ALIASES.get(stem, stem)


def _department_matches_company(department: str, company: str) -> bool:
	"""True when Department link belongs to the given company."""
	if not department or not company:
		return False
	dept_company = frappe.db.get_value("Department", department, "company")
	if dept_company:
		return dept_company == company
	abbr = frappe.db.get_value("Company", company, "abbr")
	return bool(abbr and department.endswith(f" - {abbr}"))


def resolve_department_name(department_value, company=None):
	"""Resolve stem or link to ERPNext Department for *company* (e.g. Finance - CWSCL)."""
	if not (department_value or "").strip():
		return None

	value = department_value.strip()
	stem = normalize_department_stem(value)
	if not stem:
		frappe.throw("Department value is invalid.")

	def pick_one(filters_list):
		"""Return the single matching department name or throw on ambiguity."""
		names = frappe.get_all(
			"Department",
			filters=filters_list + [["disabled", "=", 0]],
			pluck="name",
			order_by="name asc",
		)
		if len(names) == 1:
			return names[0]
		if len(names) > 1:
			preview = ", ".join(names[:8])
			suffix = f"... ({len(names)} total)" if len(names) > 8 else ""
			frappe.throw(
				f"Multiple Departments match '{stem}' ({preview}{suffix}). "
				"Pick an exact ERPNext Department link name."
			)
		return None

	def resolve_for_company(co: str | None) -> str | None:
		if not co:
			return None
		abbr = frappe.db.get_value("Company", co, "abbr")
		if abbr:
			candidate = f"{stem} - {abbr}".strip()
			if frappe.db.exists("Department", candidate):
				return candidate
		return pick_one([["company", "=", co], ["department_name", "=", stem]])

	# 1. Always prefer the project / target company (local Finance - C must not stick on server).
	if company:
		matched = resolve_for_company(company)
		if matched:
			return matched

	# 2. Accept an exact link only when it matches that company.
	if frappe.db.exists("Department", value):
		if not company or _department_matches_company(value, company):
			return value

	fallback_company = get_default_company()
	if fallback_company and fallback_company != company:
		matched = resolve_for_company(fallback_company)
		if matched:
			return matched

	# 3. Unique department_name across companies.
	all_match = frappe.get_all(
		"Department",
		filters=[["department_name", "=", stem], ["disabled", "=", 0]],
		pluck="name",
		order_by="name asc",
	)
	if len(all_match) == 1:
		return all_match[0]
	if len(all_match) > 1:
		frappe.throw(
			f"Multiple Departments named '{stem}' exist across companies. "
			"Set Project.company or rename one."
		)

	frappe.throw(
		f"No Department found for '{stem}'"
		+ (f" under company {company}." if company else ".")
		+ f" Create Department '{stem} - <company abbr>' for that company."
	)


# ─── Whitelisted Project Creation ────────────────────────────────────────────

INTAKE_DOCUMENT_CODES = ("CI", "PKL")


def project_has_intake_documents(project_doc) -> bool:
	"""True when CI and PKL are present on the project shipment document table."""
	if not project_doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		return False
	rows_by_code = {}
	for row in project_doc.get(SHIPMENT_DOCUMENTS_FIELD) or []:
		if not row.document_type:
			continue
		code = frappe.db.get_value("Document Type", row.document_type, "code")
		if code:
			rows_by_code[code] = row
	for code in INTAKE_DOCUMENT_CODES:
		row = rows_by_code.get(code)
		if not row or not row.attachment:
			return False
	return True


def bootstrap_project_workflow_status(project_name: str) -> None:
	"""
	After insert: move to Documents Received when CRM already supplied CI/PKL.

	Uses db.set_value to avoid Frappe's 'no transition on insert' workflow check.
	"""
	if not project_name or not frappe.db.exists("Project", project_name):
		return
	project = frappe.get_doc("Project", project_name)
	if not project.meta.has_field("custom_shipment_status"):
		return
	if project.get("custom_shipment_status") != "Draft":
		return
	if not project_has_intake_documents(project):
		return
	frappe.db.set_value(
		"Project",
		project_name,
		"custom_shipment_status",
		"Documents Received",
		update_modified=False,
	)


def insert_shipment_project(project) -> str:
	"""Insert a new shipment project and apply post-insert workflow status.

	A concurrent creation grabbing the same CGM reference is caught by the unique
	index on custom_cgm_ref_no (patch v2_39); Frappe surfaces that as a
	UniqueValidationError ("CGM Ref No must be unique") so the user can retry.
	"""
	project.insert(ignore_permissions=True)
	bootstrap_project_workflow_status(project.name)
	bootstrap_sea_task_plan_for_project(project.name)
	return project.name


@frappe.whitelist()
def backfill_intake_documents_on_sea_tasks(project):
	"""Copy Project shipment documents onto tasks 1–2 (for projects created before this feature)."""
	frappe.has_permission("Project", ptype="write", throw=True)
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
		auto_complete_initial_sea_tasks,
	)

	carried = carry_project_shipment_documents_to_sea_tasks(project)
	auto_complete_initial_sea_tasks(project)
	return {"tasks_updated": carried}


def bootstrap_sea_task_plan_for_project(project_name: str) -> dict | None:
	"""
	For Sea projects with CRM-approved CI/PKL: create the 24-task plan and auto-complete tasks 1–2.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
		auto_complete_initial_sea_tasks,
	)

	if frappe.db.get_value("Project", project_name, "custom_mode_of_transport") != "Sea":
		return None
	if not project_has_intake_documents(frappe.get_doc("Project", project_name)):
		return None

	if frappe.db.exists("Task", {"project": project_name, "custom_task_flow_key": SEA_TASK_FLOW_KEY}):
		done = auto_complete_initial_sea_tasks(project_name)
		return {"auto_completed": done, "created": 0}

	result = _create_sea_import_task_plan_internal(project_name)
	result["auto_completed"] = auto_complete_initial_sea_tasks(project_name)
	return result


@frappe.whitelist()
def create_project_from_customer(customer, project_name=None):
	"""Create a shipment project from a Customer record."""
	frappe.has_permission("Project", ptype="create", throw=True)

	if not frappe.db.exists("Customer", customer):
		frappe.throw(f"Customer {customer} not found")

	# Prevent copying data out of a source record the user cannot read.
	frappe.has_permission("Customer", ptype="read", doc=customer, throw=True)
	cust = frappe.get_doc("Customer", customer)

	shipment_type = None
	mode_of_transport = None
	lead_name = cust.get("lead_name")
	if lead_name and frappe.db.exists("Lead", lead_name):
		row = frappe.db.get_value(
			"Lead",
			lead_name,
			["custom_shipment_type", "custom_mode_of_transport"],
			as_dict=True,
		)
		if row:
			shipment_type = row.get("custom_shipment_type")
			mode_of_transport = row.get("custom_mode_of_transport")

	proj = frappe.new_doc("Project")
	proj.customer = customer
	apply_shipment_data(proj, shipment_type=shipment_type, mode=mode_of_transport)
	_apply_lead_shipment_defaults(proj, lead_name)
	_apply_project_tracking_defaults(proj)
	if project_name:
		proj.project_name = project_name
		if proj.meta.has_field("custom_cgm_ref_no"):
			proj.custom_cgm_ref_no = project_name

	project_fields = frappe.get_meta("Project")
	if lead_name and project_fields.has_field("custom_source_lead"):
		proj.custom_source_lead = lead_name

	sync_linked_attachments_to_project(proj)
	return insert_shipment_project(proj)


def _lead_field_value(lead, *candidates: str):
	"""Return the first non-empty attribute present on the Lead document."""
	lead_meta = lead.meta
	for name in candidates:
		if not lead_meta.has_field(name):
			continue
		value = lead.get(name)
		if value not in (None, ""):
			return value
	return None


def _apply_project_tracking_defaults(project) -> None:
	"""Seed tracking sheet fields on new projects (opened date; CGM ref assigned on insert)."""
	meta = project.meta
	if meta.has_field("custom_opened_date") and not project.get("custom_opened_date"):
		project.custom_opened_date = today()


def _container_rows_from_preshipment_source(source_doc) -> list[dict]:
	"""Container rows from preshipment child table, or from linked Bill of Lading when empty."""
	rows = []
	for row in source_doc.get("custom_container_information") or []:
		rows.append(
			{
				"container_number": row.get("container_number"),
				"type_of_container": row.get("type_of_container"),
			}
		)
	if rows:
		return rows

	bl_name = source_doc.get("custom_bill_of_lading")
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return []

	bl = frappe.get_doc("Bill of Lading", bl_name)
	return [
		{
			"container_number": row.get("container_number"),
			"type_of_container": row.get("type_of_container"),
		}
		for row in bl.get("container_information") or []
	]


def _copy_container_rows_to_project(project, rows: list[dict]) -> None:
	if not rows or not project.meta.has_field("custom_container_information"):
		return
	project.set("custom_container_information", [])
	for row in rows:
		project.append(
			"custom_container_information",
			{
				"container_number": row.get("container_number"),
				"type_of_container": row.get("type_of_container"),
			},
		)


def _apply_preshipment_transport_defaults(project, source_doc) -> None:
	"""Copy B/L, AWB, and container rows from Lead/Opportunity onto a new Project."""
	project_meta = project.meta

	if project_meta.has_field("custom_bill_of_lading"):
		bl = source_doc.get("custom_bill_of_lading")
		if bl and not project.get("custom_bill_of_lading"):
			project.custom_bill_of_lading = bl

	if project_meta.has_field("custom_awb_number"):
		awb = source_doc.get("custom_awb_number") or source_doc.get("custom_air_waybill")
		if awb and not project.get("custom_awb_number"):
			project.custom_awb_number = awb

	if project_meta.has_field("custom_container_information") and not project.get(
		"custom_container_information"
	):
		_copy_container_rows_to_project(project, _container_rows_from_preshipment_source(source_doc))


def _apply_lead_shipment_defaults(project, lead_name: str | None) -> None:
	"""Copy shipment hints from Lead onto Project when fields are empty."""
	if not lead_name or not frappe.db.exists("Lead", lead_name):
		return
	lead = frappe.get_doc("Lead", lead_name)
	project_meta = project.meta
	pairs = (
		("custom_consignee", _lead_field_value(lead, "company_name", "lead_name")),
		(
			"custom_shipment_description",
			_lead_field_value(lead, "description", "notes", "title"),
		),
		("custom_shipment_remarks", _lead_field_value(lead, "notes")),
	)
	for fieldname, value in pairs:
		if project_meta.has_field(fieldname) and value and not project.get(fieldname):
			project.set(fieldname, value)
	_apply_preshipment_transport_defaults(project, lead)


def lead_has_customer(lead):
	"""Return True when a Customer is already linked to this Lead."""
	if frappe.db.get_value("Customer", {"lead_name": lead}, "name"):
		return True
	lead_customer = frappe.db.get_value("Lead", lead, "customer")
	return bool(lead_customer and frappe.db.exists("Customer", lead_customer))


@frappe.whitelist()
def create_project_from_lead(lead, project_name=None):
	"""Create a shipment project from an approved Lead."""
	frappe.has_permission("Project", ptype="create", throw=True)
	# Prevent copying data out of a source record the user cannot read.
	frappe.has_permission("Lead", ptype="read", doc=lead, throw=True)
	lead_doc = frappe.get_doc("Lead", lead)

	# 1. Ensure the lead is in the correct pre-shipment status.
	if lead_doc.get("custom_cgm_preshipment_status") != "Lead Ready to Convert":
		frappe.throw("Lead must be in **Lead Ready to Convert** before creating a Project.")

	# 2. Ensure a Customer is already linked to the lead.
	if not lead_has_customer(lead):
		frappe.throw(
			"No Customer linked to this Lead. Use **Create Customer** from the Lead first, then try again."
		)

	customer = frappe.db.get_value("Customer", {"lead_name": lead}, "name") or lead_doc.customer

	# 3. Build and save the new Project.
	proj = frappe.new_doc("Project")
	proj.customer = customer
	apply_shipment_data(
		proj,
		shipment_type=lead_doc.get("custom_shipment_type"),
		mode=lead_doc.get("custom_mode_of_transport"),
	)
	_apply_lead_shipment_defaults(proj, lead)
	_apply_project_tracking_defaults(proj)
	if project_name:
		proj.project_name = project_name
		if proj.meta.has_field("custom_cgm_ref_no"):
			proj.custom_cgm_ref_no = project_name

	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_source_lead"):
		proj.custom_source_lead = lead

	from cgm_shipping.cgm_worldwide_shipping.customizations.bl_containers import (
		apply_bill_of_lading_from_source,
	)

	apply_bill_of_lading_from_source(proj, lead_doc)
	sync_linked_attachments_to_project(proj)
	return insert_shipment_project(proj)


@frappe.whitelist()
def create_project_from_opportunity(opportunity, project_name=None):
	"""Create a shipment project from an approved Opportunity."""
	frappe.has_permission("Project", ptype="create", throw=True)
	# Prevent copying data out of a source record the user cannot read.
	frappe.has_permission("Opportunity", ptype="read", doc=opportunity, throw=True)
	opp = frappe.get_doc("Opportunity", opportunity)

	# 1. Validate the opportunity status and party type.
	if opp.get("custom_cgm_preshipment_status") != "Opp Ready for Project":
		frappe.throw("Opportunity must be **Opp Ready for Project** before creating a shipment Project.")
	if opp.opportunity_from != "Customer":
		frappe.throw("Opportunity party must be a **Customer** to create a shipment Project.")

	# 2. Validate the linked customer exists.
	customer = opp.party_name
	if not frappe.db.exists("Customer", customer):
		frappe.throw(f"Customer {customer} not found")

	# 3. Build and save the new Project.
	proj = frappe.new_doc("Project")
	proj.customer = customer
	if opp.get("company"):
		proj.company = opp.company
	apply_shipment_data(
		proj,
		shipment_type=opp.get("custom_shipment_type"),
		mode=opp.get("custom_mode_of_transport"),
	)
	_apply_opportunity_fields_to_project(proj, opp)
	_apply_project_tracking_defaults(proj)
	if project_name:
		proj.project_name = project_name
		if proj.meta.has_field("custom_cgm_ref_no"):
			proj.custom_cgm_ref_no = project_name

	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_source_opportunity"):
		proj.custom_source_opportunity = opportunity

	_apply_preshipment_transport_defaults(proj, opp)
	sync_linked_attachments_to_project(proj)
	return insert_shipment_project(proj)


# ─── Sea Import Task Plan ─────────────────────────────────────────────────────


def _create_sea_import_task_plan_internal(project, reset=False):
	"""Generate ordered sea-import tasks (internal; no duplicate check unless reset)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
		auto_complete_initial_sea_tasks,
	)

	project_doc = frappe.get_doc("Project", project)
	if project_doc.get("custom_mode_of_transport") != "Sea":
		frappe.throw("This task plan is for Sea mode projects only.")

	existing = frappe.get_all(
		"Task",
		filters={"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY},
		fields=["name"],
		limit=1,
	)
	if existing and not frappe.utils.cint(reset):
		frappe.throw("Sea task plan already exists. Use reset=1 if you want to regenerate it.")
	if existing and frappe.utils.cint(reset):
		for d in frappe.get_all(
			"Task",
			filters={"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY},
			fields=["name"],
		):
			frappe.delete_doc("Task", d.name, ignore_permissions=True, force=True)

	task_template = load_sea_task_template()
	created = []
	prev_task = None

	for idx, item in enumerate(task_template, start=1):
		subject = item.get("subject")
		if not subject:
			frappe.throw(f"Task template item at position {idx} has no subject.")

		task = frappe.new_doc("Task")
		task.subject = subject
		task.project = project
		task.custom_task_flow_key = SEA_TASK_FLOW_KEY
		task.custom_sequence_no = idx
		task.department = resolve_department_name(item.get("department"), company=project_doc.company)
		task.status = "Open"
		task.insert(ignore_permissions=True)

		if prev_task:
			task.append("depends_on", {"task": prev_task.name})
			task.save(ignore_permissions=True)

		prev_task = task
		created.append(task.name)

	out = {"created": created, "count": len(created)}
	if project_has_intake_documents(project_doc):
		out["auto_completed"] = auto_complete_initial_sea_tasks(project)
	return out


@frappe.whitelist()
def create_sea_import_task_plan(project, reset=False):
	"""Generate ordered sea-import tasks and link them via a depends_on chain."""
	frappe.has_permission("Task", ptype="create", throw=True)
	return _create_sea_import_task_plan_internal(project, reset=reset)


# ─── Finance Notification ─────────────────────────────────────────────────────


@frappe.whitelist()
def notify_finance_for_task(task_name):
	"""Notify Finance users (in-app + email) that payment action is needed for a task."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_email_notifications import (
		notify_finance_for_task_email,
	)

	return notify_finance_for_task_email(task_name)


# ─── Task Payment Helpers ─────────────────────────────────────────────────────


def payment_entry_allocates_purchase_invoice(payment_entry_name, purchase_invoice_name):
	"""Return True when the Payment Entry references the given Purchase Invoice."""
	if not payment_entry_name or not purchase_invoice_name:
		return False

	pe = frappe.get_doc("Payment Entry", payment_entry_name)
	for row in pe.get("references") or []:
		if row.reference_doctype == "Purchase Invoice" and row.reference_name == purchase_invoice_name:
			return True
	return False


@frappe.whitelist()
def link_purchase_invoice_to_task(task_name, purchase_invoice):
	"""Link a submitted Purchase Invoice to a sea finance task; sync Project."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link import (
		link_purchase_invoice_to_task_enhanced,
	)

	return link_purchase_invoice_to_task_enhanced(task_name, purchase_invoice)


@frappe.whitelist()
def complete_task_with_payment(task_name, payment_entry):
	"""Attach a submitted Payment Entry to a finance task and mark it completed."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link import (
		complete_task_with_payment_enhanced,
	)

	return complete_task_with_payment_enhanced(task_name, payment_entry)
