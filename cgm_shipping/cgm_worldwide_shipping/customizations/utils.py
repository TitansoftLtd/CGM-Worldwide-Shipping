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
from cgm_shipping.cgm_worldwide_shipping.customizations.department import (  # noqa: E402,F401
	DEPARTMENT_NAME_ALIASES,
	get_department_name_stem,
	normalize_department_stem,
	resolve_department_name,
)

SEA_TASK_FLOW_KEY = "SEA_IMPORT_E2E"

from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_documents import (  # noqa: E402,F401
	CUSTOMER_ATTACH_TO_DOCUMENT_CODE,
	DOCUMENT_TYPE_DEFAULTS,
	OPPORTUNITY_DOCUMENTS_FIELD,
	SHIPMENT_DOCUMENTS_FIELD,
	TASK_DOCUMENTS_FIELD,
	append_task_document_row,
	append_verified_doc_row,
	carry_bill_of_lading_attachment_to_project,
	carry_clients_documents_to_project,
	carry_customer_attachments_to_project,
	carry_preshipment_docs_to_project,
	carry_project_shipment_documents_to_sea_tasks,
	carry_task_documents_to_project,
	document_types_match,
	ensure_document_types,
	ensure_project_shipment_documents_field,
	get_bill_of_lading_attachment_url,
	get_document_type_link_name,
	get_preshipment_attachments,
	get_project_documents_fieldname,
	refresh_project_shipment_documents,
	refresh_projects_for_customer,
	sync_linked_attachments_to_project,
	sync_project_shipment_documents,
)



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

# (Shipment-document carrying/sync helpers now live in shipment_documents.py — re-exported at top.)

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


# (Department resolution helpers now live in department.py — re-exported at top.)

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
