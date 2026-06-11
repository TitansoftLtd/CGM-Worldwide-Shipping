import frappe
from frappe.utils import now_datetime, today

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	INTAKE_DOCUMENT_CODES,
	PERMIT_REGISTER_FIELD,
	SHIPMENT_DOCUMENTS_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
	carry_bill_of_lading_attachment_to_project,
	carry_clients_documents_to_project,
	get_opportunity_documents_field,
	get_project_shipment_documents_field,
	sync_documents,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
	bootstrap_sea_task_plan_for_project,
	enforce_workflow_task_gate,
	get_sea_closure_blockers,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	apply_shipment_data,
	assign_cgm_project_reference,
	get_awb_value_from_doc,
	get_bl_container_child_field,
	get_project_awb_field,
	is_cgm_ref,
	normalize_shipment_fields_on_doc,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	get_bl_config,
	get_container_table_field_for_doctype,
	get_field_from_meta,
	get_link_field_for_doctype,
)


# ─── Shipment Document Table ──────────────────────────────────────────────────
def get_documents(doc):
	return doc.get(SHIPMENT_DOCUMENTS_FIELD) or []

# ─── Workflow Stage Requirements ─────────────────────────────────────────────
def get_stage_requirements():
	"""Map Project shipment status to required Document Type stages (from CGM Shipping Settings)."""
	settings = frappe.get_single("CGM Shipping Settings")
	rows = sorted(
		settings.get("custom_workflow_stage_requirements") or [],
		key=lambda r: ((r.shipment_workflow_state or "").strip(), r.idx or 0),
	)
	out = {}
	for row in rows:
		state = (row.shipment_workflow_state or "").strip()
		stage = (row.required_stage or "").strip()
		if not state or not stage:
			continue
		out.setdefault(state, []).append(stage)
	return out


# ─── Project Save Hooks ───────────────────────────────────────────────────────
def assign_cgm_reference_on_insert(doc, _method=None):
	"""Allocate CGM/FCL001/0526 as project_name and custom_cgm_ref_no on new shipments."""
	if is_cgm_ref(doc.project_name) or is_cgm_ref(doc.get("custom_cgm_ref_no")):
		assign_cgm_project_reference(doc)
		return
	if doc.project_name and not str(doc.project_name).startswith("Shipment -"):
		return
	assign_cgm_project_reference(doc)

def sync_consignee_from_customer(doc, _method=None):
	"""Keep consignee aligned with the linked customer."""
	if not doc.get("customer") or not doc.meta.has_field("custom_consignee"):
		return

	customer_label = frappe.db.get_value("Customer", doc.customer, "customer_name") or doc.customer
	if not doc.get("custom_consignee") or doc.has_value_changed("customer"):
		doc.custom_consignee = customer_label

def apply_shipment_document_automation(doc, _method=None):
	# Legacy workflow statuses that existed before we switched Project tracking to
	# the ordered CGM Sea chart (UCR Applied → ... → Completed).
	# Map them before Select validation runs on save.
	if doc.meta.has_field("custom_shipment_status"):
		legacy_status = doc.get("custom_shipment_status")
		legacy_map = {
			"IDF Created": "UCR Applied",
			"Permits Processing": "Pre-clearance",
			"Awaiting Arrival": "Client Inspection",
		}
		if legacy_status in legacy_map:
			doc.custom_shipment_status = legacy_map[legacy_status]

	# Legacy transport location label used in older projects.
	if doc.meta.has_field("custom_current_location"):
		legacy_location = doc.get("custom_current_location")
		if legacy_location == "Origin Country":
			doc.custom_current_location = "At origin"

	# Re-normalising shipment type/mode is idempotent, so only run it when those
	# fields actually change (or on a new doc) - skips a Document-Type lookup per save.
	if (
		doc.is_new()
		or doc.has_value_changed("custom_shipment_type")
		or doc.has_value_changed("custom_mode_of_transport")
	):
		normalize_shipment_fields_on_doc(doc)
	# 1. Pull files from linked Lead, Customer, and Tasks into shipment documents.
	if not frappe.flags.get("cgm_syncing_shipment_documents"):
		sync_documents(doc)
	# 2. Normalise row status and uploader/verifier metadata.
	normalize_document_rows(doc)
	normalize_permit_register_rows(doc)
	# 3. Block workflow changes when required documents are missing.
	enforce_document_gate_on_workflow_change(doc)
	# 4. Require CI/PKL before Documents Received.
	enforce_intake_documents_before_documents_received(doc)
	# 5. Sea only: workflow states require prior sea tasks completed in chart order.
	enforce_sea_workflow_task_gates(doc)
	# 6. IDF / entry: all permits must be Post-Cleared before Entry Lodged.
	enforce_permits_post_cleared_before_entry_lodged(doc)
	# 7. Project Completed only when tasks, docs, permits, payments, and billing are done.
	enforce_project_closure_on_workflow_change(doc)

def _shipment_document_row_map(doc):
	rows = {}
	for row in get_documents(doc):
		if row.document_type:
			rows[row.document_type] = row
	return rows

def _required_document_types(mode, stages=None):
	"""Document Type names required for a mode (and optional workflow stages).

	``mode_of_transport`` is a Table MultiSelect: a Document Type applies to
	``mode`` when it lists that mode, or to every mode when it lists none.
	"""
	if not mode:
		return []
	filters = {"default_required": 1}
	if stages:
		filters["required_stage"] = ["in", stages]
	candidates = frappe.get_all(
		"Document Type",
		filters=filters,
		pluck="name",
		order_by="required_stage asc, name asc",
	)
	if not candidates:
		return []
	mode_rows = frappe.get_all(
		"Mode of Transport Item",
		filters={"parenttype": "Document Type", "parent": ["in", candidates]},
		fields=["parent", "mode_of_transport"],
	)
	modes_by_dt = {}
	for row in mode_rows:
		modes_by_dt.setdefault(row.parent, set()).add(row.mode_of_transport)
	# Keep candidate ordering; a Document Type with no modes applies to all modes.
	return [
		name
		for name in candidates
		if not modes_by_dt.get(name) or mode in modes_by_dt[name]
	]

def normalize_document_rows(doc):
	rows = list(get_documents(doc))
	# Batch the Document Type 'default_required' lookups (was one query per row).
	doc_types = {r.document_type for r in rows if r.document_type}
	required_map = {}
	if doc_types:
		required_map = {
			d.name: d.default_required
			for d in frappe.get_all(
				"Document Type",
				filters={"name": ["in", list(doc_types)]},
				fields=["name", "default_required"],
			)
		}
	for row in rows:
		# 1. Sync the required flag from the Document Type master.
		if row.document_type:
			default_required = required_map.get(row.document_type)
			if default_required is not None:
				row.required = int(default_required)

		# 2. Auto-manage upload state and uploader metadata.
		if row.attachment:
			if row.status in (None, "", "Missing"):
				row.status = "Uploaded"
			if not row.uploaded_by:
				row.uploaded_by = frappe.session.user
			if not row.uploaded_on:
				row.uploaded_on = now_datetime()
		else:
			row.status = "Missing"
			row.uploaded_by = None
			row.uploaded_on = None
			row.verified_by = None
			row.verified_on = None

		# 3. Sync verification metadata from status.
		if row.status in ("Verified", "Rejected"):
			if not row.attachment:
				label = row.document_type or "a document"
				frappe.throw(f"Attach a file before marking {label} as {row.status}.")
			if not row.verified_by:
				row.verified_by = frappe.session.user
			if not row.verified_on:
				row.verified_on = now_datetime()
		elif row.status == "Uploaded":
			row.verified_by = None
			row.verified_on = None

def enforce_document_gate_on_workflow_change(doc):
	# 1. Detect a shipment status change.
	prev = doc.get_doc_before_save()
	if not prev:
		return
	prev_status = prev.get("custom_shipment_status")
	new_status = doc.get("custom_shipment_status")
	if not new_status or new_status == prev_status:
		return

	# 2. Load required document stages for the target status.
	stage_requirements = get_stage_requirements()
	required_stages = stage_requirements.get(new_status)
	if not required_stages:
		return

	# 3. Find required documents that are not yet verified.
	mode = doc.get("custom_mode_of_transport")
	rows_by_type = _shipment_document_row_map(doc)
	missing = []
	for dt_name in _required_document_types(mode, required_stages):
		row = rows_by_type.get(dt_name)
		if not row or not row.attachment or row.status != "Verified":
			missing.append(dt_name)

	# 4. Stop the workflow move when evidence is incomplete.
	if missing:
		labels = ", ".join(sorted(set(missing)))
		frappe.throw(f"Cannot move shipment to <b>{new_status}</b>. Verify required documents first: {labels}")

def enforce_sea_workflow_task_gates(doc):
	"""Sea import: each workflow state requires prior tasks in the 24-step clearance chart."""
	prev = doc.get_doc_before_save()
	if not prev:
		return
	prev_status = prev.get("custom_shipment_status")
	new_status = doc.get("custom_shipment_status")
	if not new_status or new_status == prev_status:
		return
	if doc.get("custom_mode_of_transport") != "Sea":
		return
	enforce_workflow_task_gate(doc.name, new_status)

def enforce_intake_documents_before_documents_received(doc):
	prev = doc.get_doc_before_save()
	if not prev or prev.get("custom_shipment_status") == doc.get("custom_shipment_status"):
		return
	if doc.get("custom_shipment_status") != "Documents Received":
		return
	missing = []
	rows_by_code = {}
	for row in get_documents(doc):
		if not row.document_type:
			continue
		code = frappe.db.get_value("Document Type", row.document_type, "code")
		if code:
			rows_by_code[code] = row
	for code in INTAKE_DOCUMENT_CODES:
		row = rows_by_code.get(code)
		if not row or not row.attachment or row.status == "Missing":
			label = frappe.db.get_value("Document Type", {"code": code}, "name") or code
			missing.append(label)
	if missing:
		frappe.throw(
			f"Upload client documents in <b>Client Documents</b> first: {', '.join(missing)}. "
			"Use <b>custom_shipment_documents</b> - not Permit Register."
		)

def normalize_permit_register_rows(doc):
	"""Derive Pre-Cleared / Post-Cleared from invoice, payment, and permit document fields."""
	if not doc.meta.has_field(PERMIT_REGISTER_FIELD):
		return
	for row in doc.get(PERMIT_REGISTER_FIELD) or []:
		row.clearance_phase = derive_permit_clearance_phase(row)

def derive_permit_clearance_phase(row) -> str:
	"""Map permit row finance fields to high-level clearance phase (see OPERATIONS_PROCESS.md §7)."""
	if row.get("payment_entry"):
		pe_status = frappe.db.get_value("Payment Entry", row.payment_entry, "docstatus")
		if int(pe_status or 0) == 1:
			return "Post-Cleared"
	if row.get("receipt_verified") and row.get("permit_document"):
		return "Post-Cleared"
	if row.get("status") in ("Approved", "Released") and row.get("receipt_verified"):
		return "Post-Cleared"
	if row.get("invoice_verified") and (
		row.get("payment_invoice") or row.get("purchase_invoice") or row.get("payment_entry")
	):
		return "Pre-Cleared"
	if row.get("payment_invoice") or row.get("status") in (
		"Invoice Submitted",
		"Invoice Verified",
		"Paid",
		"Receipt Submitted",
	):
		return "Pre-Cleared"
	return "Not Started"

def enforce_permits_post_cleared_before_entry_lodged(doc):
	prev = doc.get_doc_before_save()
	if not prev:
		return
	prev_status = prev.get("custom_shipment_status")
	new_status = doc.get("custom_shipment_status")
	if not new_status or new_status == prev_status or new_status != "Entry Lodged":
		return
	if not doc.meta.has_field(PERMIT_REGISTER_FIELD):
		return
	pending = [
		r.permit_type or "Permit"
		for r in doc.get(PERMIT_REGISTER_FIELD) or []
		if derive_permit_clearance_phase(r) != "Post-Cleared"
	]
	if pending:
		frappe.throw(
			"Cannot lodge customs entry until all permits are <b>Post-Cleared</b> "
			f"(payment, receipt verified, permit document issued). Pending: {', '.join(pending)}."
	)

def enforce_project_closure_on_workflow_change(doc):
	"""FINAL RULE: Completed only when tasks, documents, permits, payments, and customer invoice are done."""
	prev = doc.get_doc_before_save()
	if not prev:
		return
	prev_status = prev.get("custom_shipment_status")
	new_status = doc.get("custom_shipment_status")
	if not new_status or new_status == prev_status or new_status != "Completed":
		return

	blockers = []

	if doc.get("custom_mode_of_transport") == "Sea":
		blockers.extend(get_sea_closure_blockers(doc.name))
	else:
		open_tasks = frappe.get_all(
			"Task",
			filters={"project": doc.name, "status": ["not in", ["Completed", "Cancelled"]]},
			pluck="subject",
			limit=10,
		)
		if open_tasks:
			preview = ", ".join(open_tasks[:5])
			if len(open_tasks) > 5:
				preview += f" (+{len(open_tasks) - 5} more)"
			blockers.append(f"Open tasks: {preview}")

	mode = doc.get("custom_mode_of_transport")
	rows_by_type = _shipment_document_row_map(doc)
	for dt_name in _required_document_types(mode):
		row = rows_by_type.get(dt_name)
		if not row or not row.attachment or row.status != "Verified":
			blockers.append(f"Document not verified: {dt_name}")

	if doc.meta.has_field(PERMIT_REGISTER_FIELD):
		not_cleared = [
			r.permit_type or "Permit"
			for r in doc.get(PERMIT_REGISTER_FIELD) or []
			if derive_permit_clearance_phase(r) != "Post-Cleared"
		]
		if not_cleared:
			blockers.append(f"Permits not Post-Cleared: {', '.join(not_cleared)}")

	# Completed payable tasks must have a submitted Payment Entry:
	payable_done_no_pe = frappe.db.sql(
		"""
		SELECT t.subject
		FROM `tabTask` t
		WHERE t.project = %s
		  AND t.status = 'Completed'
		  AND t.custom_purchase_invoice IS NOT NULL AND t.custom_purchase_invoice != ''
		  AND (t.custom_payment_entry IS NULL OR t.custom_payment_entry = '')
		LIMIT 5
		""",
		doc.name,
		as_dict=True,
	)
	if payable_done_no_pe:
		blockers.append(
			"Completed tasks missing Payment Entry: "
			+ ", ".join(r.subject for r in payable_done_no_pe)
		)

	if not frappe.db.exists(
		"Sales Invoice", {"project": doc.name, "docstatus": 1}
	):
		blockers.append("No submitted Sales Invoice linked to this Project")

	if blockers:
		frappe.throw(
			"<b>Cannot mark Project as Completed.</b> Resolve first:<ul>"
			+ "".join(f"<li>{b}</li>" for b in blockers)
			+ "</ul>"
		)

# ─── Project creation from Lead / Opportunity (moved from utils.py) ───────────
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
	"""Copy B/L, AWB, and container rows from Opportunity onto a new Project."""
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

def apply_opportunity_to_project_mappings(project, opp) -> None:
	"""Copy scalar Opportunity shipment fields onto Project when the target is empty."""
	meta = project.meta
	pairs = (
		("custom_entry_no", "custom_entry_no"),
		("custom_consignee", "custom_consignee"),
		("custom_quantity", "custom_quantity"),
		("custom_vessel", "custom_vessel"),
		("custom_gross_weight", "custom_gross_weightkg"),
		("custom_weight_nw", "custom_net_weightkg"),
		("custom_description_of_goods", "custom_description_of_goods"),
		("custom_clearance_station", "custom_clearance_station"),
		("custom_station_code", "custom_station_code"),
		("custom_country_of_origin", "custom_country_of_origin"),
	)
	for src_field, dest_field in pairs:
		if not meta.has_field(dest_field) or not opp.meta.has_field(src_field):
			continue
		value = opp.get(src_field)
		if value not in (None, "") and not project.get(dest_field):
			project.set(dest_field, value)

def sync_predocuments_from_source(project, source_doc) -> None:
	"""Pull client docs and B/L attachment from Opportunity onto Project shipment documents."""
	bl_config = get_bl_config()
	bl_link_field = bl_config.get("opportunity_bl_field") or get_link_field_for_doctype(
		"Opportunity", "Bill of Lading"
	)
	clients_field = get_opportunity_documents_field()
	if clients_field and source_doc.meta.has_field(clients_field):
		carry_clients_documents_to_project(project, source_doc)
	sync_documents(project)
	project_bl = project.get(bl_link_field) if bl_link_field else None
	source_bl = source_doc.get(bl_link_field) if bl_link_field else None
	carry_bill_of_lading_attachment_to_project(
		project,
		bl_name=project_bl or source_bl,
		source_doc=source_doc,
	)

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

	# 2. Enforce one Project per Opportunity: return the existing one instead of
	# branching a duplicate.
	if frappe.get_meta("Project").has_field("custom_source_opportunity"):
		existing = frappe.db.get_value(
			"Project", {"custom_source_opportunity": opportunity}, "name"
		)
		if existing:
			return existing

	# 3. Validate the linked customer exists.
	customer = opp.party_name
	if not frappe.db.exists("Customer", customer):
		frappe.throw(f"Customer {customer} not found")

	# 4. Build and save the new Project.
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
	sync_predocuments_from_source(proj, opp)
	return insert_shipment_project(proj)
