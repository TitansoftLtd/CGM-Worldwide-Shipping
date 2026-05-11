import frappe
from frappe import _
from pathlib import Path
import json
from frappe.utils import now_datetime

SEA_TASK_FLOW_KEY = "SEA_IMPORT_E2E"
# Step 1: map template labels or old dept names -> ERPNext `department_name` (before company suffix).
DEPARTMENT_NAME_ALIASES = {
	"Administration": "Documentation",
}


def build_project_name_seed(label, shipment_type=None, mode=None):
	# Step 1: prepare readable base name for repeated jobs.
	core = (label or "").strip() or "Client"
	details = " ".join(part for part in [shipment_type, mode] if part)
	if details:
		return _("Shipment - {0} - {1}").format(core, details)
	return _("Shipment - {0}").format(core)


def ensure_unique_project_name(seed_name):
	# Step 1: trim and use fallback when blank.
	base = (seed_name or "").strip() or _("Shipment")
	# Step 2: use base when no duplicate exists.
	if not frappe.db.exists("Project", {"project_name": base}):
		return base
	# Step 3: append sequence suffix to avoid collisions.
	for idx in range(2, 1000):
		candidate = f"{base} ({idx})"
		if not frappe.db.exists("Project", {"project_name": candidate}):
			return candidate
	frappe.throw(_("Could not generate a unique Project Name. Please set a custom name manually."))


def get_default_company():
	# Step 1: try user default company.
	company = frappe.defaults.get_user_default("Company")
	if company:
		return company
	# Step 2: use global default company.
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if company:
		return company
	# Step 3: fallback to first available company.
	names = frappe.get_all("Company", limit=1, pluck="name")
	return names[0] if names else None


def apply_shipment_data(project, shipment_type=None, mode=None):
	# Step 1: set shipment classification values.
	if shipment_type:
		project.custom_shipment_type = shipment_type
	if mode:
		project.custom_mode_of_transport = mode
	# Step 2: initialize sea workflow starting status.
	if frappe.get_meta("Project").has_field("custom_shipment_status"):
		project.custom_shipment_status = "Documents Received"


def get_project_documents_fieldname():
	# Step 1: prefer plural table field on Project.
	meta = frappe.get_meta("Project")
	if meta.has_field("custom_shipment_documents"):
		return "custom_shipment_documents"
	# Step 2: fallback for legacy singular fieldname.
	return "custom_shipment_document"


def get_preshipment_attachments(source_doc):
	# Step 1: read explicit CI/PKL fields when available.
	attachments = {"CI": None, "PKL": None}
	for code in ("CI", "PKL"):
		fieldname = f"custom_{code.lower()}_attachment"
		if source_doc.meta.has_field(fieldname):
			attachments[code] = source_doc.get(fieldname)

	# Step 2: fallback to source timeline attachments for old records.
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
			"commercial invoice" in filename or filename.startswith("ci") or "_ci" in filename or "-ci" in filename
		):
			attachments["CI"] = file_row.file_url
		if not attachments["PKL"] and (
			"packing list" in filename or filename.startswith("pkl") or "_pkl" in filename or "-pkl" in filename
		):
			attachments["PKL"] = file_row.file_url
		if attachments["CI"] and attachments["PKL"]:
			break
	return attachments


def append_verified_doc_row(project_doc, document_type, attachment_url):
	if not attachment_url:
		return
	fieldname = get_project_documents_fieldname()
	rows = project_doc.get(fieldname) or []
	for row in rows:
		if row.document_type == document_type:
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
		fieldname,
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


def carry_preshipment_docs_to_project(project_doc, source_doc):
	# Step 1: collect CI/PKL files from source CRM document.
	attachments = get_preshipment_attachments(source_doc)
	# Step 2: copy CI and PKL files into Project shipment document rows.
	append_verified_doc_row(project_doc, "CI", attachments.get("CI"))
	append_verified_doc_row(project_doc, "PKL", attachments.get("PKL"))


def get_document_type_link_name(code):
	"""Resolve `Document Type` name for child table links (code may differ from name)."""
	if not code:
		return None
	name = frappe.db.get_value("Document Type", {"code": code}, "name")
	if name:
		return name
	if frappe.db.exists("Document Type", code):
		return code
	return None


def carry_customer_kra_pin_to_project(project_doc, customer_ref):
	"""Copy KRA PIN file from Customer onboarding field into Project shipment documents."""
	if not customer_ref:
		return
	if getattr(customer_ref, "doctype", None) == "Customer":
		customer_doc = customer_ref
	else:
		if not frappe.db.exists("Customer", customer_ref):
			return
		customer_doc = frappe.get_doc("Customer", customer_ref)

	meta_c = frappe.get_meta("Customer")
	if not meta_c.has_field("custom_kra_pin_attachment"):
		return

	attach = customer_doc.get("custom_kra_pin_attachment")
	if not attach:
		return

	doctype_name = get_document_type_link_name("KRA_PIN")
	if not doctype_name:
		return

	append_verified_doc_row(project_doc, doctype_name, attach)


def load_sea_task_template():
	# Step 1: load reusable process document from JSON file.
	template_path = Path(__file__).parent / "data" / "sea_import_task_template.json"
	if not template_path.exists():
		frappe.throw(_("Sea task template file is missing: {0}").format(template_path.name))
	data = json.loads(template_path.read_text())
	# Step 2: validate minimal structure.
	if not isinstance(data, list) or not data:
		frappe.throw(_("Sea task template must contain at least one task."))
	return data


def get_department_name_stem(raw):
	# Step 1: tolerate full doc names like `Finance - CWSCL` stored in templates.
	value = (raw or "").strip()
	if not value:
		return ""
	# Step 2: ERPNext dept docnames are commonly `{department_name} - {abbr}`.
	if " - " in value:
		return value.split(" - ", 1)[0].strip()
	return value


def resolve_department_name(department_value, company=None):
	# Step 1: blank means no assignment.
	if not (department_value or "").strip():
		return None

	value = department_value.strip()
	# Step 2: accept exact ERPNext department link name when it already matches this site.
	if frappe.db.exists("Department", value):
		return value

	stem = get_department_name_stem(value)
	stem = DEPARTMENT_NAME_ALIASES.get(stem, stem)
	if not stem:
		frappe.throw(_("Department value is invalid."))

	# Step 3: narrow by project's company first (preferred for multi-company sites).
	def pick_one(filters_list):
		names = frappe.get_all(
			"Department",
			filters=filters_list + [["disabled", "=", 0]],
			pluck="name",
			order_by="name asc",
		)
		if len(names) == 1:
			return names[0]
		if len(names) > 1:
			frappe.throw(
				_("Multiple Departments match '{0}' ({1}). Pick an exact ERPNext Department link name.")
				.format(stem, ", ".join(names[:8]))
				+ (f"... ({len(names)} total)" if len(names) > 8 else "")
			)
		return None

	if company:
		matched = pick_one([["company", "=", company], ["department_name", "=", stem]])
		if matched:
			return matched

	fallback_company = get_default_company()
	if fallback_company and fallback_company != company:
		matched = pick_one(
			[["company", "=", fallback_company], ["department_name", "=", stem]],
		)
		if matched:
			return matched

	# Step 4: resolve by department_name only when unique across enabled departments.
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
			_("Multiple Departments named '{0}' exist across companies. Set Project.company or rename one.")
			.format(stem)
		)

	# Step 5: try composed docname `{stem} - {abbr}` using project or default company.
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
		_("No Department found for '{0}'. Create it under the Project company or set an exact department link name.")
		.format(stem)
	)


@frappe.whitelist()
def create_project_from_customer(customer, project_name=None):
	"""Create shipment project from Customer defaults."""
	frappe.has_permission("Project", ptype="create", throw=True)
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found").format(customer))

	cust = frappe.get_doc("Customer", customer)
	company = get_default_company()
	if not company:
		frappe.throw(_("Set a default Company first."))

	# Step 1: shipment classification comes from source Lead (if any), not Customer.
	shipment_type = None
	mode_of_transport = None
	if cust.get("lead_name") and frappe.db.exists("Lead", cust.lead_name):
		row = frappe.db.get_value(
			"Lead",
			cust.lead_name,
			["custom_shipment_type", "custom_mode_of_transport"],
			as_dict=True,
		)
		if row:
			shipment_type = row.get("custom_shipment_type")
			mode_of_transport = row.get("custom_mode_of_transport")

	proj = frappe.new_doc("Project")
	proj.customer = customer
	proj.company = company
	seed_name = project_name or build_project_name_seed(
		cust.customer_name or customer,
		shipment_type=shipment_type,
		mode=mode_of_transport,
	)
	proj.project_name = ensure_unique_project_name(seed_name)
	apply_shipment_data(
		proj,
		shipment_type=shipment_type,
		mode=mode_of_transport,
	)
	if cust.get("lead_name") and frappe.get_meta("Project").has_field("custom_source_lead"):
		proj.custom_source_lead = cust.lead_name
	if cust.get("lead_name") and frappe.db.exists("Lead", cust.lead_name):
		lead_doc = frappe.get_doc("Lead", cust.lead_name)
		carry_preshipment_docs_to_project(proj, lead_doc)
	carry_customer_kra_pin_to_project(proj, cust)

	proj.insert()
	return proj.name


@frappe.whitelist()
def create_project_from_lead(lead, project_name=None):
	"""Create shipment project from approved Lead."""
	frappe.has_permission("Project", ptype="create", throw=True)
	lead_doc = frappe.get_doc("Lead", lead)

	if lead_doc.get("custom_cgm_preshipment_status") != "Lead Ready to Convert":
		frappe.throw(_("Lead must be in **Lead Ready to Convert** before creating a Project."))

	customer = frappe.db.get_value("Customer", {"lead_name": lead}, "name")
	if not customer:
		frappe.throw(
			_(
				"No Customer linked to this Lead. Use **Create Customer** from the Lead first, then try again."
			)
		)

	company = get_default_company()
	if not company:
		frappe.throw(_("Set a default Company first."))

	proj = frappe.new_doc("Project")
	proj.customer = customer
	proj.company = company
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
	if frappe.get_meta("Project").has_field("custom_source_lead"):
		proj.custom_source_lead = lead
	carry_preshipment_docs_to_project(proj, lead_doc)
	carry_customer_kra_pin_to_project(proj, customer)

	proj.insert()
	return proj.name


@frappe.whitelist()
def create_project_from_opportunity(opportunity, project_name=None):
	"""Create shipment project from approved Opportunity."""
	frappe.has_permission("Project", ptype="create", throw=True)
	opp = frappe.get_doc("Opportunity", opportunity)

	if opp.get("custom_cgm_preshipment_status") != "Opp Ready for Project":
		frappe.throw(_("Opportunity must be **Opp Ready for Project** before creating a shipment Project."))

	if opp.opportunity_from != "Customer":
		frappe.throw(_("Opportunity party must be a **Customer** to create a shipment Project."))

	customer = opp.party_name
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found").format(customer))

	company = get_default_company() or opp.company
	if not company:
		frappe.throw(_("Set a default Company or set Opportunity company."))

	proj = frappe.new_doc("Project")
	proj.customer = customer
	proj.company = company
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
	if frappe.get_meta("Project").has_field("custom_source_opportunity"):
		proj.custom_source_opportunity = opportunity
	carry_preshipment_docs_to_project(proj, opp)
	carry_customer_kra_pin_to_project(proj, customer)

	proj.insert()
	return proj.name


@frappe.whitelist()
def create_sea_import_task_plan(project, reset=False):
	"""Generate ordered sea-import tasks using Task doctype and depends_on chain."""
	frappe.has_permission("Task", ptype="create", throw=True)
	project_doc = frappe.get_doc("Project", project)
	if project_doc.get("custom_mode_of_transport") != "Sea":
		frappe.throw(_("This task plan is for Sea mode projects only."))

	existing = frappe.get_all(
		"Task",
		filters={"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY},
		fields=["name"],
		limit=1,
	)
	if existing and not frappe.utils.cint(reset):
		frappe.throw(_("Sea task plan already exists. Use reset=1 if you want to regenerate it."))
	if existing and frappe.utils.cint(reset):
		for d in frappe.get_all(
			"Task", filters={"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY}, fields=["name"]
		):
			frappe.delete_doc("Task", d.name, ignore_permissions=True, force=True)

	# Step 1: load reusable standard task set.
	task_template = load_sea_task_template()
	created = []
	prev_task = None
	# Step 2: create tasks in sequence and link via depends_on.
	for idx, item in enumerate(task_template, start=1):
		subject = item.get("subject")
		if not subject:
			frappe.throw(_("Task template item at position {0} has no subject.").format(idx))
		task = frappe.new_doc("Task")
		task.subject = subject
		task.project = project
		task.custom_task_flow_key = SEA_TASK_FLOW_KEY
		task.custom_sequence_no = idx
		task.department = resolve_department_name(item.get("department"), company=project_doc.company)
		task.expected_time = item.get("expected_time") or 0
		task.status = "Open"
		task.insert(ignore_permissions=True)
		if prev_task:
			task.append("depends_on", {"task": prev_task.name})
			task.save(ignore_permissions=True)
		prev_task = task
		created.append(task.name)

	return {"created": created, "count": len(created)}


@frappe.whitelist()
def notify_finance_for_task(task_name):
	"""Notify finance users that payment action is needed for a task."""
	if not task_name or not frappe.db.exists("Task", task_name):
		return {"notified": 0}

	task = frappe.get_doc("Task", task_name)
	subject = f"Payment action needed for task {task.name}"
	if frappe.db.exists(
		"Notification Log",
		{"document_type": "Task", "document_name": task.name, "subject": subject},
	):
		return {"notified": 0}

	finance_users = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ["Finance Manager", "Accounts User", "Accounts Manager"]]},
		fields=["parent"],
	)
	unique_users = []
	for row in finance_users:
		user = row.parent
		if user in unique_users:
			continue
		if not frappe.db.get_value("User", user, "enabled"):
			continue
		unique_users.append(user)

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


def is_sea_ucr_idf_task_one(task):
	"""Sea import template, Task 1 — UCR / IDF purchase invoice + payment flow."""
	return (
		task.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY
		and int(task.get("custom_sequence_no") or 0) == 1
	)


def payment_entry_allocates_purchase_invoice(payment_entry_name, purchase_invoice_name):
	if not payment_entry_name or not purchase_invoice_name:
		return False
	pe = frappe.get_doc("Payment Entry", payment_entry_name)
	for row in pe.get("references") or []:
		if row.reference_doctype == "Purchase Invoice" and row.reference_name == purchase_invoice_name:
			return True
	return False


@frappe.whitelist()
def link_purchase_invoice_to_task(task_name, purchase_invoice):
	"""After Purchase Invoice is submitted, link it to sea Task 1 (UCR/IDF)."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(_("Task not found."))
	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw(_("Purchase Invoice not found."))

	task = frappe.get_doc("Task", task_name)
	if not is_sea_ucr_idf_task_one(task):
		frappe.throw(_("This action is only for sea import Task 1 (UCR / IDF)."))

	pi_status = frappe.db.get_value("Purchase Invoice", purchase_invoice, "docstatus")
	if int(pi_status or 0) != 1:
		frappe.throw(_("Purchase Invoice must be submitted before linking to the task."))

	if frappe.get_meta("Task").has_field("custom_purchase_invoice"):
		task.custom_purchase_invoice = purchase_invoice
	task.save(ignore_permissions=True)

	notify_finance_for_task(task.name)

	return {"task": task.name, "purchase_invoice": purchase_invoice}


@frappe.whitelist()
def complete_task_with_payment(task_name, payment_entry):
	"""Attach submitted Payment Entry (paying the task's PI) and mark Task 1 completed."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(_("Task {0} not found").format(task_name))
	if not payment_entry or not frappe.db.exists("Payment Entry", payment_entry):
		frappe.throw(_("Payment Entry {0} not found").format(payment_entry))

	payment_status = frappe.db.get_value("Payment Entry", payment_entry, "docstatus")
	if int(payment_status or 0) != 1:
		frappe.throw(_("Payment Entry must be submitted before linking it to the task."))

	task = frappe.get_doc("Task", task_name)
	if is_sea_ucr_idf_task_one(task) and frappe.get_meta("Task").has_field("custom_purchase_invoice"):
		pi_name = task.get("custom_purchase_invoice")
		if not pi_name:
			frappe.throw(
				_("Create and submit a Purchase Invoice for the IDF fees, link it using **Create Purchase Invoice** on the task, then record payment.")
			)
		if not payment_entry_allocates_purchase_invoice(payment_entry, pi_name):
			frappe.throw(
				_("Payment Entry must allocate against Purchase Invoice {0}.").format(pi_name)
			)

	if frappe.get_meta("Task").has_field("custom_payment_entry"):
		task.custom_payment_entry = payment_entry
	task.completed_by = frappe.session.user
	task.completed_on = now_datetime()
	task.status = "Completed"
	task.save(ignore_permissions=True)

	return {"task": task.name, "status": task.status}
