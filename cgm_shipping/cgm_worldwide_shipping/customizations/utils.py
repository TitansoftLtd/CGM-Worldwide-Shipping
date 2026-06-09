import re

import frappe
from frappe.utils import getdate, now_datetime, today
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
from cgm_shipping.cgm_worldwide_shipping.customizations.department import (  # noqa: E402,F401
	DEPARTMENT_NAME_ALIASES,
	get_department_name_stem,
	normalize_department_stem,
	resolve_department_name,
)


from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_documents import (  # noqa: E402,F401
	CUSTOMER_ATTACH_TO_DOCUMENT_CODE,
	OPPORTUNITY_DOCUMENTS_FIELD,
	SHIPMENT_DOCUMENTS_FIELD,
	TASK_DOCUMENTS_FIELD,
	append_task_document_row,
	append_verified_doc_row,
	carry_customer_attachments_to_project,
	carry_preshipment_docs_to_project,
	carry_project_shipment_documents_to_sea_tasks,
	carry_task_documents_to_project,
	ensure_project_shipment_documents_field,
	get_preshipment_attachments,
	get_project_documents_fieldname,
	refresh_project_shipment_documents,
	refresh_projects_for_customer,
	sync_linked_attachments_to_project,
	sync_project_shipment_documents,
)


# ─── Dynamic field discovery ───────────────────────────────────────────────────


def get_field_from_meta(doctype: str, keyword: str) -> str | None:
	"""Find the first fieldname on a DocType that contains keyword."""
	return next(
		(
			field.fieldname
			for field in frappe.get_meta(doctype).fields
			if keyword in field.fieldname
		),
		None,
	)


def get_link_field_for_doctype(doctype: str, target_doctype: str) -> str | None:
	"""Find a Link field on doctype that points to target_doctype."""
	return next(
		(
			field.fieldname
			for field in frappe.get_meta(doctype).fields
			if field.fieldtype == "Link" and field.options == target_doctype
		),
		None,
	)


def get_container_table_field_for_doctype(doctype: str) -> str | None:
	"""Find a child table on doctype whose rows include container_number."""
	return next(
		(
			field.fieldname
			for field in frappe.get_meta(doctype).fields
			if field.fieldtype == "Table"
			and frappe.get_meta(field.options)
			and frappe.get_meta(field.options).has_field("container_number")
		),
		None,
	)


def get_opportunity_documents_field() -> str | None:
	"""Fetch the Clients Documents table fieldname from Opportunity meta."""
	return next(
		(
			field.fieldname
			for field in frappe.get_meta("Opportunity").fields
			if field.fieldtype == "Table"
			and "clients_documents" in field.fieldname
		),
		None,
	)


def get_project_shipment_documents_field() -> str | None:
	"""Fetch the Shipment Documents table fieldname from Project meta."""
	return next(
		(
			field.fieldname
			for field in frappe.get_meta("Project").fields
			if field.fieldtype == "Table"
			and "shipment_documents" in field.fieldname
		),
		None,
	)


@frappe.request_cache
def get_bl_config() -> dict:
	"""Fetch Bill of Lading config from Document Type master - no hardcoding."""
	dt_meta = frappe.get_meta("Document Type")
	config_fields = [
		name
		for name in (
			"linked_doctype",
			"attachment_field",
			"opportunity_bl_field",
			"opportunity_quantity_field",
			"opportunity_container_field",
			"opportunity_source_field",
		)
		if dt_meta.has_field(name)
	]
	config = {}
	if config_fields and dt_meta.has_field("linked_doctype"):
		config = (
			frappe.db.get_value(
				"Document Type",
				{"linked_doctype": "Bill of Lading"},
				config_fields,
				as_dict=True,
			)
			or {}
		)

	if not config.get("attachment_field"):
		config["attachment_field"] = get_field_from_meta("Bill of Lading", "attach_bill")
	if not config.get("opportunity_bl_field"):
		config["opportunity_bl_field"] = get_link_field_for_doctype("Opportunity", "Bill of Lading")
	if not config.get("opportunity_quantity_field"):
		bl_field = config.get("opportunity_bl_field")
		if bl_field:
			config["opportunity_quantity_field"] = get_quantity_field_after("Opportunity", bl_field)
	if not config.get("opportunity_container_field"):
		config["opportunity_container_field"] = get_container_table_field_for_doctype("Opportunity")
	if not config.get("opportunity_source_field"):
		config["opportunity_source_field"] = get_link_field_for_doctype("Bill of Lading", "Opportunity")
	return config


def get_quantity_field_after(doctype: str, anchor_field: str) -> str | None:
	"""First Data/Float/Int field after anchor_field in DocType field order."""
	fields = frappe.get_meta(doctype).fields
	start = next((idx for idx, field in enumerate(fields) if field.fieldname == anchor_field), -1)
	if start < 0:
		return None
	for field in fields[start + 1 :]:
		if field.fieldtype in ("Section Break", "Tab Break"):
			break
		if field.fieldtype == "Table":
			break
		if field.fieldtype in ("Data", "Float", "Int"):
			return field.fieldname
	return None


def get_bl_container_child_field() -> str | None:
	"""Child table on Bill of Lading that holds container rows."""
	return get_container_table_field_for_doctype("Bill of Lading")


def get_awb_value_from_doc(doc) -> str | None:
	"""Return the first non-empty AWB-style field value on a document."""
	for field in doc.meta.fields:
		if field.fieldtype not in ("Data", "Link", "Small Text"):
			continue
		name = field.fieldname.lower()
		if not any(token in name for token in ("awb", "airway", "air_waybill")):
			continue
		value = doc.get(field.fieldname)
		if value not in (None, ""):
			return value
	return None


def get_project_awb_field() -> str | None:
	"""AWB field on Project."""
	return get_field_from_meta("Project", "awb_number") or get_field_from_meta("Project", "awb")

# ─── Document Type utilities ──────────────────────────────────────────────────
def document_types_match(existing_type, incoming_type):
	"""Check if two document types match by name or code."""
	if not existing_type or not incoming_type:
		return False
	if existing_type == incoming_type:
		return True
	existing_code = frappe.db.get_value("Document Type", existing_type, "code")
	incoming_code = frappe.db.get_value("Document Type", incoming_type, "code")
	return bool(existing_code and incoming_code and existing_code == incoming_code)

def get_document_type_link_name(code):
	"""Get the name of a Document Type by its code."""
	if not code:
		return None
	name = frappe.db.get_value("Document Type", {"code": code}, "name")
	if name:
		return name
	if frappe.db.exists("Document Type", code):
		return code
	return None

def ensure_document_types():
	"""Create default Document Type records if they don't exist."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_documents import DOCUMENT_TYPE_DEFAULTS

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

def carry_clients_documents_to_project(project_doc, source_doc) -> None:
	"""Copy all Clients Documents rows from Opportunity onto Project shipment documents."""
	clients_field = get_opportunity_documents_field()
	shipment_field = get_project_shipment_documents_field()
	if not source_doc or not clients_field or not source_doc.meta.has_field(clients_field):
		return
	if not shipment_field or not project_doc.meta.has_field(shipment_field):
		return

	ensure_document_types()
	for row in source_doc.get(clients_field) or []:
		if not row.document_type or not row.attachment:
			continue
		if not frappe.db.exists("Document Type", row.document_type):
			continue
		append_or_update_shipment_document_row(project_doc, row)

def append_or_update_shipment_document_row(project_doc, source_row) -> None:
	shipment_field = get_project_shipment_documents_field()
	if not shipment_field:
		return
	rows = project_doc.get(shipment_field) or []
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
		shipment_field,
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
	bl_config = get_bl_config()
	attachment_field = bl_config.get("attachment_field")
	if bl_name and frappe.db.exists("Bill of Lading", bl_name) and attachment_field:
		attachment_url = frappe.db.get_value("Bill of Lading", bl_name, attachment_field)
		if attachment_url:
			return attachment_url

	if not source_doc:
		return None

	clients_field = get_opportunity_documents_field()
	if not clients_field or not source_doc.meta.has_field(clients_field):
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
	bl_config = get_bl_config()
	bl_link_field = bl_config.get("opportunity_bl_field") or get_link_field_for_doctype(
		"Project", "Bill of Lading"
	)
	bl_name = bl_name or (project_doc.get(bl_link_field) if bl_link_field else None)
	attachment_url = get_bill_of_lading_attachment_url(bl_name, source_doc)
	if not attachment_url:
		return

	document_type = get_document_type_link_name("BL")
	if document_type:
		append_verified_doc_row(project_doc, document_type, attachment_url)


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

# (Department resolution helpers now live in department.py - re-exported at top.)

# ─── Whitelisted Project Creation ────────────────────────────────────────────
INTAKE_DOCUMENT_CODES = ("CI", "PKL")

def project_has_intake_documents(project_doc) -> bool:
	"""True when CI and PKL are present on the project shipment document table."""
	shipment_field = get_project_shipment_documents_field()
	if not shipment_field or not project_doc.meta.has_field(shipment_field):
		return False
	rows_by_code = {}
	for row in project_doc.get(shipment_field) or []:
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

	project_doc = frappe.get_doc("Project", project_name)
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_reference import (
		sea_import_enabled_for_project,
	)

	if not sea_import_enabled_for_project(project_doc):
		return None
	if not project_has_intake_documents(project_doc):
		return None

	if frappe.db.exists("Task", {"project": project_name, "custom_task_flow_key": SEA_TASK_FLOW_KEY}):
		done = auto_complete_initial_sea_tasks(project_name)
		return {"auto_completed": done, "created": 0}

	result = create_sea_import_task_plan_internal(project_name)
	result["auto_completed"] = auto_complete_initial_sea_tasks(project_name)
	return result

def get_lead_field_value(lead, *candidates: str):
	"""Return the first non-empty attribute present on the Lead document."""
	lead_meta = lead.meta
	for name in candidates:
		if not lead_meta.has_field(name):
			continue
		value = lead.get(name)
		if value not in (None, ""):
			return value
	return None

def apply_project_tracking_defaults(project) -> None:
	"""Seed tracking sheet fields on new projects (opened date; CGM ref assigned on insert)."""
	opened_date_field = get_field_from_meta("Project", "opened_date")
	if opened_date_field and not project.get(opened_date_field):
		project.set(opened_date_field, today())

def get_container_rows_from_preshipment_source(source_doc) -> list[dict]:
	"""Container rows from preshipment child table, or from linked Bill of Lading when empty."""
	bl_config = get_bl_config()
	container_field = bl_config.get("opportunity_container_field") or get_container_table_field_for_doctype(
		source_doc.doctype
	)
	rows = []
	if container_field:
		for row in source_doc.get(container_field) or []:
			rows.append(
				{
					"container_number": row.get("container_number"),
					"type_of_container": row.get("type_of_container"),
				}
			)
	if rows:
		return rows

	bl_link_field = bl_config.get("opportunity_bl_field") or get_link_field_for_doctype(
		source_doc.doctype, "Bill of Lading"
	)
	bl_name = source_doc.get(bl_link_field) if bl_link_field else None
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return []

	bl = frappe.get_doc("Bill of Lading", bl_name)
	bl_container_field = get_bl_container_child_field()
	return [
		{
			"container_number": row.get("container_number"),
			"type_of_container": row.get("type_of_container"),
		}
		for row in bl.get(bl_container_field) or []
	]

def copy_container_rows_to_project(project, rows: list[dict]) -> None:
	container_field = get_container_table_field_for_doctype("Project")
	if not rows or not container_field or not project.meta.has_field(container_field):
		return
	project.set(container_field, [])
	for row in rows:
		project.append(
			container_field,
			{
				"container_number": row.get("container_number"),
				"type_of_container": row.get("type_of_container"),
			},
		)

def apply_preshipment_transport_defaults(project, source_doc) -> None:
	"""Copy B/L, AWB, and container rows from Lead/Opportunity onto a new Project."""
	bl_config = get_bl_config()
	project_meta = project.meta
	source_bl_field = bl_config.get("opportunity_bl_field") or get_link_field_for_doctype(
		source_doc.doctype, "Bill of Lading"
	)
	project_bl_field = bl_config.get("opportunity_bl_field") or get_link_field_for_doctype(
		"Project", "Bill of Lading"
	)

	if project_bl_field and project_meta.has_field(project_bl_field) and source_bl_field:
		bl = source_doc.get(source_bl_field)
		if bl and not project.get(project_bl_field):
			project.set(project_bl_field, bl)

	project_awb_field = get_project_awb_field()
	if project_awb_field and project_meta.has_field(project_awb_field):
		awb = get_awb_value_from_doc(source_doc)
		if awb and not project.get(project_awb_field):
			project.set(project_awb_field, awb)

	container_field = get_container_table_field_for_doctype("Project")
	if container_field and project_meta.has_field(container_field) and not project.get(container_field):
		copy_container_rows_to_project(project, get_container_rows_from_preshipment_source(source_doc))


def apply_lead_shipment_defaults(project, lead_name: str | None) -> None:
	"""Copy shipment hints from Lead onto Project when fields are empty."""
	if not lead_name or not frappe.db.exists("Lead", lead_name):
		return
	lead = frappe.get_doc("Lead", lead_name)
	project_meta = project.meta
	pairs = (
		("custom_consignee", get_lead_field_value(lead, "company_name", "lead_name")),
		(
			"custom_shipment_description",
			get_lead_field_value(lead, "description", "notes", "title"),
		),
		("custom_shipment_remarks", get_lead_field_value(lead, "notes")),
	)
	for fieldname, value in pairs:
		if project_meta.has_field(fieldname) and value and not project.get(fieldname):
			project.set(fieldname, value)
	apply_preshipment_transport_defaults(project, lead)

def apply_opportunity_to_project_mappings(project, opp) -> None:
	"""Copy scalar Opportunity shipment fields onto Project when the target is empty."""
	meta = project.meta
	pairs = (
		("custom_entry_no", "custom_entry_no"),
		("custom_batch_no", "custom_batch_no"),
		("custom_consignee", "custom_consignee"),
		("custom_quantity", "custom_shipment_quantity"),
		("custom_vesselairline", "custom_vessel_flight"),
		("custom_gross_weight", "custom_gross_weightkg"),
		("custom_weight_nw", "custom_net_weightkg"),
		("custom_description_of_goods", "custom_shipment_description"),
	)
	for src_field, dest_field in pairs:
		if not meta.has_field(dest_field) or not opp.meta.has_field(src_field):
			continue
		value = opp.get(src_field)
		if value not in (None, "") and not project.get(dest_field):
			project.set(dest_field, value)

def sync_preshipment_documents_from_source(project, source_doc) -> None:
	"""Pull client docs and B/L attachment from Lead/Opportunity onto Project shipment documents."""
	bl_config = get_bl_config()
	bl_link_field = bl_config.get("opportunity_bl_field") or get_link_field_for_doctype(
		"Opportunity", "Bill of Lading"
	)
	clients_field = get_opportunity_documents_field()
	if clients_field and source_doc.meta.has_field(clients_field):
		carry_clients_documents_to_project(project, source_doc)
	sync_linked_attachments_to_project(project)
	project_bl = project.get(bl_link_field) if bl_link_field else None
	source_bl = source_doc.get(bl_link_field) if bl_link_field else None
	carry_bill_of_lading_attachment_to_project(
		project,
		bl_name=project_bl or source_bl,
		source_doc=source_doc,
	)

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
	apply_lead_shipment_defaults(proj, lead)
	apply_project_tracking_defaults(proj)
	if project_name:
		proj.project_name = project_name
		cgm_ref_field = get_field_from_meta("Project", "cgm_ref_no")
		if cgm_ref_field:
			proj.set(cgm_ref_field, project_name)

	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_source_lead"):
		proj.custom_source_lead = lead

	from cgm_shipping.cgm_worldwide_shipping.customizations.bl_containers import (
		apply_bill_of_lading_from_source,
	)

	apply_bill_of_lading_from_source(proj, lead_doc)
	sync_preshipment_documents_from_source(proj, lead_doc)
	return insert_shipment_project(proj)

@frappe.whitelist()
def create_project_from_opportunity(opportunity, project_name=None):
	"""Create a shipment project from an approved Opportunity."""
	frappe.has_permission("Project", ptype="create", throw=True)
	# Prevent copying data out of a source record the user cannot read.
	frappe.has_permission("Opportunity", ptype="read", doc=opportunity, throw=True)
	opp = frappe.get_doc("Opportunity", opportunity)

	# 1. Validate the opportunity status and party type. The shipment Project is
	# created off the CGM Opportunity Pre-Shipment workflow: the Opportunity must
	# be Approved before it can branch into a Project.
	if opp.get("workflow_state") != "Approved":
		frappe.throw("Opportunity must be **Approved** before creating a shipment Project.")
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
	apply_project_tracking_defaults(proj)
	if project_name:
		proj.project_name = project_name
		cgm_ref_field = get_field_from_meta("Project", "cgm_ref_no")
		if cgm_ref_field:
			proj.set(cgm_ref_field, project_name)

	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_source_opportunity"):
		proj.custom_source_opportunity = opportunity

	apply_opportunity_to_project_mappings(proj, opp)
	apply_preshipment_transport_defaults(proj, opp)
	sync_preshipment_documents_from_source(proj, opp)
	return insert_shipment_project(proj)


# ─── Sea Import Task Plan ─────────────────────────────────────────────────────
def create_sea_import_task_plan_internal(project, reset=False):
	"""Generate ordered sea-import tasks (internal; no duplicate check unless reset)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
		auto_complete_initial_sea_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
		ensure_sea_task_requirements_configured,
	)

	ensure_sea_task_requirements_configured()

	project_doc = frappe.get_doc("Project", project)
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_reference import (
		sea_import_enabled_for_project,
	)

	if not sea_import_enabled_for_project(project_doc):
		frappe.throw("This task plan is for sea-import shipment types only.")

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
	return create_sea_import_task_plan_internal(project, reset=reset)


# ─── Finance Notification ─────────────────────────────────────────────────────
@frappe.whitelist()
def notify_finance_for_task(task_name):
	"""Notify Finance users (in-app + email) that payment action is needed for a task."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.notifications_service import (
		notify_finance_for_task as _notify,
	)

	return _notify(task_name)


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
