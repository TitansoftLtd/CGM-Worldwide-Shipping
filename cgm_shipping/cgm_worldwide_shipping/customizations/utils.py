import frappe
from erpnext import get_default_company
from frappe.utils import now_datetime

SEA_TASK_FLOW_KEY = "SEA_IMPORT_E2E"

# Map template labels or old department names -> ERPNext department_name (before company suffix).
DEPARTMENT_NAME_ALIASES = {
	"Administration": "Documentation",
}


# ─── Project Name Helpers ────────────────────────────────────────────────────


def build_project_name_seed(label, shipment_type=None, mode=None):
	# 1. Build a readable base name for the project.
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
	# 1. Set shipment classification fields on the project.
	if shipment_type:
		project.custom_shipment_type = shipment_type
	if mode:
		project.custom_mode_of_transport = mode

	# 2. Initialise the sea workflow status when the field exists.
	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_shipment_status"):
		project.custom_shipment_status = "Documents Received"


SHIPMENT_DOCUMENTS_FIELD = "custom_shipment_documents"


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
		carry_preshipment_docs_to_project(project_doc, frappe.get_doc("Lead", lead_name))

	# 2. Opportunity source when present.
	opp_name = project_doc.get("custom_source_opportunity")
	if opp_name and frappe.db.exists("Opportunity", opp_name):
		carry_preshipment_docs_to_project(project_doc, frappe.get_doc("Opportunity", opp_name))

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
		dept = (row.department or "").strip()
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


def resolve_department_name(department_value, company=None):
	"""Resolve a raw department string to a valid ERPNext Department link name."""
	if not (department_value or "").strip():
		return None

	value = department_value.strip()

	# 1. Accept the value as-is when it already matches an ERPNext Department.
	if frappe.db.exists("Department", value):
		return value

	# 2. Strip the company suffix and apply any known aliases.
	stem = get_department_name_stem(value)
	stem = DEPARTMENT_NAME_ALIASES.get(stem, stem)
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

	# 3. Try to narrow the match using the project's company first.
	if company:
		matched = pick_one([["company", "=", company], ["department_name", "=", stem]])
		if matched:
			return matched

	# 4. Try the global default company as a fallback.
	fallback_company = get_default_company()
	if fallback_company and fallback_company != company:
		matched = pick_one([["company", "=", fallback_company], ["department_name", "=", stem]])
		if matched:
			return matched

	# 5. Match by department_name alone when the name is unique across all companies.
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

	# 6. Try composing the docname as `{stem} - {abbr}` for the project and default companies.
	for co in [company, fallback_company]:
		if not co:
			continue
		abbr = frappe.db.get_value("Company", co, "abbr")
		if not abbr:
			continue
		candidate = f"{stem} - {abbr}".strip()
		if frappe.db.exists("Department", candidate):
			return candidate

	frappe.throw(
		f"No Department found for '{stem}'. "
		"Create it under the Project company or set an exact department link name."
	)


# ─── Whitelisted Project Creation ────────────────────────────────────────────


@frappe.whitelist()
def create_project_from_customer(customer, project_name=None):
	"""Create a shipment project from a Customer record."""
	frappe.has_permission("Project", ptype="create", throw=True)

	# 1. Validate the customer exists.
	if not frappe.db.exists("Customer", customer):
		frappe.throw(f"Customer {customer} not found")

	cust = frappe.get_doc("Customer", customer)

	# 2. Pull shipment classification from the linked Lead when available.
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

	# 3. Build and save the new Project.
	proj = frappe.new_doc("Project")
	proj.customer = customer
	seed_name = project_name or build_project_name_seed(
		cust.customer_name or customer,
		shipment_type=shipment_type,
		mode=mode_of_transport,
	)
	proj.project_name = ensure_unique_project_name(seed_name)
	apply_shipment_data(proj, shipment_type=shipment_type, mode=mode_of_transport)

	# 4. Link the source lead and sync shipment documents.
	project_fields = frappe.get_meta("Project")
	if lead_name and project_fields.has_field("custom_source_lead"):
		proj.custom_source_lead = lead_name

	sync_linked_attachments_to_project(proj)
	proj.insert()
	return proj.name


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
	seed_name = project_name or build_project_name_seed(
		lead_doc.company_name or lead_doc.lead_name or lead,
		shipment_type=lead_doc.get("custom_shipment_type"),
		mode=lead_doc.get("custom_mode_of_transport"),
	)
	proj.project_name = ensure_unique_project_name(seed_name)
	apply_shipment_data(
		proj,
		shipment_type=lead_doc.get("custom_shipment_type"),
		mode=lead_doc.get("custom_mode_of_transport"),
	)

	# 4. Link the source lead and carry pre-shipment documents across.
	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_source_lead"):
		proj.custom_source_lead = lead

	sync_linked_attachments_to_project(proj)
	proj.insert()
	return proj.name


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
	seed_name = project_name or build_project_name_seed(
		opp.customer_name or opportunity,
		shipment_type=opp.get("custom_shipment_type"),
		mode=opp.get("custom_mode_of_transport"),
	)
	proj.project_name = ensure_unique_project_name(seed_name)
	apply_shipment_data(
		proj,
		shipment_type=opp.get("custom_shipment_type"),
		mode=opp.get("custom_mode_of_transport"),
	)

	# 4. Link the source opportunity and carry pre-shipment documents across.
	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_source_opportunity"):
		proj.custom_source_opportunity = opportunity

	sync_linked_attachments_to_project(proj)
	proj.insert()
	return proj.name


# ─── Sea Import Task Plan ─────────────────────────────────────────────────────


@frappe.whitelist()
def create_sea_import_task_plan(project, reset=False):
	"""Generate ordered sea-import tasks and link them via a depends_on chain."""
	frappe.has_permission("Task", ptype="create", throw=True)
	project_doc = frappe.get_doc("Project", project)

	# 1. Guard: this plan is only for Sea mode projects.
	if project_doc.get("custom_mode_of_transport") != "Sea":
		frappe.throw("This task plan is for Sea mode projects only.")

	# 2. Check for an existing plan and handle the reset flag.
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

	# 3. Load the standard sea task template.
	task_template = load_sea_task_template()
	created = []
	prev_task = None

	# 4. Create each task in sequence and link it to the previous via depends_on.
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

	return {"created": created, "count": len(created)}


# ─── Finance Notification ─────────────────────────────────────────────────────


@frappe.whitelist()
def notify_finance_for_task(task_name):
	"""Notify finance users that payment action is needed for a task."""
	if not task_name or not frappe.db.exists("Task", task_name):
		return {"notified": 0}

	task = frappe.get_doc("Task", task_name)
	subject = f"Payment action needed for task {task.name}"

	# 1. Skip when this notification has already been sent.
	if frappe.db.exists(
		"Notification Log",
		{"document_type": "Task", "document_name": task.name, "subject": subject},
	):
		return {"notified": 0}

	# 2. Collect unique, enabled finance users.
	finance_users = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ["Finance Manager", "Accounts User", "Accounts Manager"]]},
		fields=["parent"],
	)
	seen = set()
	unique_users = []
	for row in finance_users:
		user = row.parent
		if user in seen:
			continue
		seen.add(user)
		if frappe.db.get_value("User", user, "enabled"):
			unique_users.append(user)

	# 3. Create a Notification Log entry for each finance user.
	count = 0
	for user in unique_users:
		log = frappe.new_doc("Notification Log")
		log.for_user = user
		log.type = "Alert"
		log.from_user = frappe.session.user
		log.document_type = "Task"
		log.document_name = task.name
		log.subject = subject
		log.insert(ignore_permissions=True)
		count += 1

	return {"notified": count}


# ─── Task Payment Helpers ─────────────────────────────────────────────────────


def is_sea_ucr_idf_task_one(task):
	"""Return True when this is Sea import Task 1 (UCR / IDF flow)."""
	return (
		task.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY
		and int(task.get("custom_sequence_no") or 0) == 1
	)


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
	"""Link a submitted Purchase Invoice to sea Task 1 (UCR/IDF) and notify finance."""
	# 1. Validate that the task and purchase invoice both exist.
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw("Purchase Invoice not found.")

	task = frappe.get_doc("Task", task_name)

	# 2. Guard: this action is only valid for sea import Task 1.
	if not is_sea_ucr_idf_task_one(task):
		frappe.throw("This action is only for sea import Task 1 (UCR / IDF).")

	# 3. Require the Purchase Invoice to be submitted before linking.
	pi_status = frappe.db.get_value("Purchase Invoice", purchase_invoice, "docstatus")
	if int(pi_status or 0) != 1:
		frappe.throw("Purchase Invoice must be submitted before linking to the task.")

	# 4. Save the link and notify finance.
	task_fields = frappe.get_meta("Task")
	if task_fields.has_field("custom_purchase_invoice"):
		task.custom_purchase_invoice = purchase_invoice
	task.save(ignore_permissions=True)
	notify_finance_for_task(task.name)

	return {"task": task.name, "purchase_invoice": purchase_invoice}


@frappe.whitelist()
def complete_task_with_payment(task_name, payment_entry):
	"""Attach a submitted Payment Entry to Task 1 and mark the task completed."""
	# 1. Validate that the task and payment entry both exist.
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(f"Task {task_name} not found")
	if not payment_entry or not frappe.db.exists("Payment Entry", payment_entry):
		frappe.throw(f"Payment Entry {payment_entry} not found")

	# 2. Require the Payment Entry to be submitted.
	payment_status = frappe.db.get_value("Payment Entry", payment_entry, "docstatus")
	if int(payment_status or 0) != 1:
		frappe.throw("Payment Entry must be submitted before linking it to the task.")

	task = frappe.get_doc("Task", task_name)

	# 3. For Task 1, verify the payment allocates against the task's Purchase Invoice.
	task_fields = frappe.get_meta("Task")
	if is_sea_ucr_idf_task_one(task) and task_fields.has_field("custom_purchase_invoice"):
		pi_name = task.get("custom_purchase_invoice")
		if not pi_name:
			frappe.throw(
				"Create and submit a Purchase Invoice for the IDF fees, "
				"link it using **Create Purchase Invoice** on the task, then record payment."
			)
		if not payment_entry_allocates_purchase_invoice(payment_entry, pi_name):
			frappe.throw(f"Payment Entry must allocate against Purchase Invoice {pi_name}.")

	# 4. Record the payment, mark the task completed, and save.
	if task_fields.has_field("custom_payment_entry"):
		task.custom_payment_entry = payment_entry
	task.completed_by = frappe.session.user
	task.completed_on = now_datetime()
	task.status = "Completed"
	task.save(ignore_permissions=True)

	return {"task": task.name, "status": task.status}
