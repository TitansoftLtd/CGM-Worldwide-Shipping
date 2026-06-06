import re

import frappe
from erpnext import get_default_company
from frappe.utils import getdate, now_datetime, today

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY

# Map template labels or old department names -> ERPNext department_name (before company suffix).
DEPARTMENT_NAME_ALIASES = {
	"Administration": "Documentation",
}


# ─── CGM reference / Project Name ─────────────────────────────────────────────
# Tracking sheet format: CGM/FCL001/1022  (prefix + 3-digit seq + MMYY period)


CGM_REF_PATTERN = re.compile(r"^CGM/[A-Z]{2,5}\d{3}/\d{4}$")


def is_cgm_ref(value: str | None) -> bool:
	if not value:
		return False
	return bool(CGM_REF_PATTERN.match(str(value).strip().upper()))


def cgm_ref_prefix(shipment_type=None, mode=None) -> str:
	"""Map shipment classification to tracking-sheet prefix (FCL, LCL, IM, …)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_type.service import (
		cgm_ref_prefix_from_master,
	)

	st = (shipment_type or "").strip()
	prefix = cgm_ref_prefix_from_master(st, mode)
	if prefix:
		return prefix

	mode = (mode or "").strip()
	if st == "Import":
		if mode == "Sea":
			return "FCL"
		if mode == "Air":
			return "AIR"
		if mode == "Road":
			return "ROD"
		return "IM"
	if st == "Export":
		return "EX"
	if mode == "Sea":
		return "FCL"
	if mode == "Air":
		return "AIR"
	if mode == "Road":
		return "ROD"
	return "IM"


def _next_cgm_ref_sequence(prefix: str, period: str) -> int:
	"""Next 3-digit sequence for CGM/{prefix}NNN/{period} in this calendar month."""
	like = f"CGM/{prefix}%/{period}"
	rows = frappe.db.sql(
		"""
		SELECT project_name AS ref FROM `tabProject` WHERE UPPER(project_name) LIKE %s
		UNION
		SELECT custom_cgm_ref_no AS ref FROM `tabProject`
		WHERE custom_cgm_ref_no IS NOT NULL AND custom_cgm_ref_no != ''
		  AND UPPER(custom_cgm_ref_no) LIKE %s
		""",
		(like.upper(), like.upper()),
		as_dict=True,
	)
	seq_pattern = re.compile(rf"^CGM/{re.escape(prefix)}(\d{{3}})/{re.escape(period)}$")
	max_seq = 0
	for row in rows:
		ref = (row.ref or "").strip().upper()
		match = seq_pattern.match(ref)
		if match:
			max_seq = max(max_seq, int(match.group(1)))
	return max_seq + 1


def build_cgm_ref_no(shipment_type=None, mode=None, opened_date=None) -> str:
	"""Allocate CGM/LCL001/1022-style reference for the shipment tracking sheet."""
	prefix = cgm_ref_prefix(shipment_type, mode)
	dt = getdate(opened_date or today())
	period = dt.strftime("%m%y")
	seq = _next_cgm_ref_sequence(prefix, period)
	for candidate_seq in range(seq, seq + 1000):
		ref = f"CGM/{prefix}{candidate_seq:03d}/{period}"
		if not frappe.db.exists("Project", {"project_name": ref}):
			return ref
	frappe.throw("Could not allocate a unique CGM reference number.")


def assign_cgm_project_reference(project) -> None:
	"""Set project_name and custom_cgm_ref_no to the tracking-sheet CGM reference."""
	if project.get("custom_cgm_ref_no") and is_cgm_ref(project.custom_cgm_ref_no):
		if not is_cgm_ref(project.project_name):
			project.project_name = project.custom_cgm_ref_no
		return

	if project.project_name and is_cgm_ref(project.project_name):
		if project.meta.has_field("custom_cgm_ref_no") and not project.get("custom_cgm_ref_no"):
			project.custom_cgm_ref_no = project.project_name
		return

	ref = build_cgm_ref_no(
		normalize_shipment_classification(
			project.get("custom_shipment_type"),
			project.get("custom_mode_of_transport"),
		)[0],
		project.get("custom_mode_of_transport"),
		project.get("custom_opened_date"),
	)
	project.project_name = ref
	if project.meta.has_field("custom_cgm_ref_no"):
		project.custom_cgm_ref_no = ref


def build_project_name_seed(label, shipment_type=None, mode=None):
	# Legacy helper — prefer assign_cgm_project_reference for new shipments.
	core = (label or "").strip() or "Client"
	details = " ".join(part for part in [shipment_type, mode] if part)
	if details:
		return f"Shipment - {core} - {details}"
	return f"Shipment - {core}"


def ensure_unique_project_name(seed_name):
	# 1. Use fallback when seed is blank.
	base = (seed_name or "").strip() or "Shipment"

	# 2. Return base name when no duplicate exists.
	if not frappe.db.exists("Project", {"project_name": base}):
		return base

	# 3. Append a numeric suffix until a unique name is found.
	for idx in range(2, 1000):
		candidate = f"{base} ({idx})"
		if not frappe.db.exists("Project", {"project_name": candidate}):
			return candidate

	frappe.throw("Could not generate a unique Project Name. Please set a custom name manually.")


# ─── Project Field Helpers ────────────────────────────────────────────────────


def apply_shipment_data(project, shipment_type=None, mode=None):
	"""Set shipment classification; derive mode from operational shipment type when known."""
	if shipment_type:
		project.custom_shipment_type = shipment_type
	if mode and project.meta.has_field("custom_mode_of_transport"):
		project.custom_mode_of_transport = mode

	normalized_type, derived_mode = normalize_shipment_classification(
		project.get("custom_shipment_type"),
		project.get("custom_mode_of_transport"),
	)
	if normalized_type:
		project.custom_shipment_type = normalized_type
	if derived_mode and project.meta.has_field("custom_mode_of_transport"):
		project.custom_mode_of_transport = derived_mode

	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_shipment_status"):
		project.custom_shipment_status = "Draft"


def normalize_shipment_classification(shipment_type=None, mode=None):
	"""
	Return (shipment_type, mode) using operational types (Sea FCL, Air Import, …).

	Legacy CRM values (Import/Export + Sea/Air/Road) are mapped for old records only.
	"""
	st = (shipment_type or "").strip()
	m = (mode or "").strip()

	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_type.service import (
		get_shipment_type_record,
		mode_from_master,
	)

	row = get_shipment_type_record(st)
	if row:
		return row.shipment_type_name or st, mode_from_master(st) or m

	# Legacy Lead/Opportunity: Import + mode → operational default (blank mode → Sea FCL).
	if st == "Import":
		if m in ("", "Sea", None):
			return "Sea FCL", "Sea"
		if m == "Air":
			return "Air Import", "Air"
		if m == "Road":
			return "Cross-Border Road Import", "Road"
		return "Sea FCL", "Sea"
	if st == "Export":
		return "Export", m or "Sea"
	if st == "Transit":
		return "Transit", m or "Sea"
	if st == "Road Import":
		return "Cross-Border Road Import", "Road"

	return st or None, m or None


def normalize_shipment_fields_on_doc(doc) -> None:
	"""Rewrite legacy Import/Export values before Select validation on save."""
	if not doc.meta.has_field("custom_shipment_type"):
		return
	mode = doc.get("custom_mode_of_transport") if doc.meta.has_field("custom_mode_of_transport") else None
	normalized_type, derived_mode = normalize_shipment_classification(
		doc.get("custom_shipment_type"),
		mode,
	)
	if normalized_type:
		doc.custom_shipment_type = normalized_type
	if derived_mode and doc.meta.has_field("custom_mode_of_transport"):
		doc.custom_mode_of_transport = derived_mode


from cgm_shipping.cgm_worldwide_shipping.customizations.documents.service import (
	CUSTOMER_ATTACH_TO_DOCUMENT_CODE,
	DOCUMENT_TYPE_DEFAULTS,
	SHIPMENT_DOCUMENTS_FIELD,
	TASK_DOCUMENTS_FIELD,
	append_task_document_row,
	append_verified_doc_row,
	carry_customer_attachments_to_project,
	carry_preshipment_docs_to_project,
	carry_project_shipment_documents_to_sea_tasks,
	carry_task_documents_to_project,
	document_types_match,
	ensure_document_types,
	ensure_project_shipment_documents_field,
	get_document_type_link_name,
	get_preshipment_attachments,
	get_project_documents_fieldname,
	refresh_project_shipment_documents,
	refresh_projects_for_customer,
	sync_linked_attachments_to_project,
	sync_project_shipment_documents,
)


OPPORTUNITY_DOCUMENTS_FIELD = "custom_clients_documents"


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
	"""Insert a new shipment project and apply post-insert workflow status."""
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_type.service import (
		sea_import_enabled_for_project,
	)

	if not sea_import_enabled_for_project(project_doc):
		return None
	if not project_has_intake_documents(project_doc):
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
		awb = (
			source_doc.get("custom_awb_number")
			or source_doc.get("custom_airway_bill")
			or source_doc.get("custom_air_waybill")
		)
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


def _apply_opportunity_to_project_mappings(project, opp) -> None:
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


def _sync_preshipment_documents_from_source(project, source_doc) -> None:
	"""Pull client docs and B/L attachment from Lead/Opportunity onto Project shipment documents."""
	if source_doc.meta.has_field(OPPORTUNITY_DOCUMENTS_FIELD):
		carry_clients_documents_to_project(project, source_doc)
	sync_linked_attachments_to_project(project)
	carry_bill_of_lading_attachment_to_project(
		project,
		bl_name=project.get("custom_bill_of_lading") or source_doc.get("custom_bill_of_lading"),
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
	_sync_preshipment_documents_from_source(proj, lead_doc)
	return insert_shipment_project(proj)


@frappe.whitelist()
def create_project_from_opportunity(opportunity, project_name=None):
	"""Create a shipment project from an approved Opportunity."""
	frappe.has_permission("Project", ptype="create", throw=True)
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
	_apply_project_tracking_defaults(proj)
	if project_name:
		proj.project_name = project_name
		if proj.meta.has_field("custom_cgm_ref_no"):
			proj.custom_cgm_ref_no = project_name

	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_source_opportunity"):
		proj.custom_source_opportunity = opportunity

	_apply_opportunity_to_project_mappings(proj, opp)
	_apply_preshipment_transport_defaults(proj, opp)
	_sync_preshipment_documents_from_source(proj, opp)
	return insert_shipment_project(proj)


# ─── Sea Import Task Plan ─────────────────────────────────────────────────────


def _create_sea_import_task_plan_internal(project, reset=False):
	"""Generate ordered sea-import tasks (internal; no duplicate check unless reset)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
		auto_complete_initial_sea_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.service import (
		ensure_sea_task_requirements_configured,
	)

	ensure_sea_task_requirements_configured()

	project_doc = frappe.get_doc("Project", project)
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_type.service import (
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
	return _create_sea_import_task_plan_internal(project, reset=reset)


# ─── Finance Notification ─────────────────────────────────────────────────────


@frappe.whitelist()
def notify_finance_for_task(task_name):
	"""Notify Finance users (in-app + email) that payment action is needed for a task."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.notifications.service import (
		notify_finance_for_task as _notify,
	)

	return _notify(task_name)


# ─── Task Payment Helpers ─────────────────────────────────────────────────────


def is_sea_ucr_idf_task_one(task):
	"""Legacy alias: finance payment tasks in the sea clearance chart."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
		is_sea_payment_task,
	)

	return is_sea_payment_task(task)


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
