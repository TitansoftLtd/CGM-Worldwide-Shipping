import frappe
from frappe.utils import getdate, now_datetime, today

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	APPROVED_WORKFLOW_STATE,
	INTAKE_DOCUMENT_CODES,
	PERMIT_REGISTER_FIELD,
	SHIPMENT_DOCUMENTS_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
	get_project_shipment_documents_field,
	is_shipment_document_verified,
	primary_attachment,
	refresh_project_documents,
	sync_documents,
	sync_project_documents_from_opportunity,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
	enforce_workflow_task_gate,
	get_sea_closure_blockers,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment import (
	copy_opportunity_scalars_to_project,
	resolve_fcl_batch_for_opportunity,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
	assign_lp_project_reference,
	is_lp_project_reference,
	refresh_project_reference_from_fields,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	apply_awb_fields_to_doc,
	apply_bill_of_lading_from_source,
	copy_carrier_fields_from_source,
	copy_shipment_classification_from_source,
	copy_tracking_fields_from_source,
	awb_quantity_summary,
	get_awb_value_from_doc,
	get_bl_quantity_summary,
	get_project_awb_field,
	normalize_shipment_fields_on_doc,
	sync_cargo_type_from_linked_bl,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	get_bl_config,
	get_field_from_meta,
	get_link_field_for_doctype,
)

# Visible on Project form (custom/project.json) and legacy column from layout patch.
PROJECT_ATA_FIELDS = ("custom_actual_time_of_arrival_ata", "custom_ata")


def _project_ata_columns() -> tuple[str, ...]:
	columns = set(frappe.db.get_table_columns("Project") or [])
	return tuple(field for field in PROJECT_ATA_FIELDS if field in columns)


def get_project_ata(doc):
	"""Return ATA from the Project, checking form field then legacy field."""
	for fieldname in PROJECT_ATA_FIELDS:
		if doc.get(fieldname):
			return getdate(doc.get(fieldname))
	return None


def build_project_ata_updates(doc, ata) -> dict:
	"""Write ATA to every Project column that stores it (form + legacy)."""
	if not ata:
		return {}
	ata_date = getdate(ata)
	return {fieldname: ata_date for fieldname in _project_ata_columns()}


def sync_project_ata_fields(doc, _method=None) -> None:
	"""Keep both ATA columns aligned whenever either one is set."""
	ata = get_project_ata(doc)
	if not ata:
		return
	for fieldname in _project_ata_columns():
		if doc.get(fieldname) != ata:
			doc.set(fieldname, ata)


def hydrate_project_ata_on_load(doc, _method=None) -> None:
	"""Backfill the visible ATA field from legacy data already on the project."""
	visible_field, legacy_field = PROJECT_ATA_FIELDS
	if visible_field not in _project_ata_columns():
		return
	if doc.get(visible_field):
		return
	legacy = doc.get(legacy_field) if legacy_field in _project_ata_columns() else None
	if not legacy:
		return
	ata = getdate(legacy)
	doc.set(visible_field, ata)
	frappe.db.set_value(
		"Project",
		doc.name,
		{visible_field: ata},
		update_modified=False,
	)


# ─── Shipment Document Table ──────────────────────────────────────────────────
def get_documents(doc):
	return doc.get(SHIPMENT_DOCUMENTS_FIELD) or []


def find_shipment_row_for_intake_code(doc, intake_code: str):
	"""Resolve a Client Documents row for CI/PKL intake codes (name or master code)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		document_type_match_tokens,
		required_document_code_is_attached,
	)

	for row in get_documents(doc):
		if not row.document_type:
			continue
		attached = document_type_match_tokens(row.document_type)
		if required_document_code_is_attached(intake_code, attached):
			return row
	return None


def intake_shipment_row_is_present(row) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import primary_attachment

	if not row:
		return False
	if not primary_attachment(row):
		return False
	return (row.status or "").strip() != "Missing"


def intake_document_label(intake_code: str) -> str:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		get_document_type_link_name,
	)

	return get_document_type_link_name(intake_code) or intake_code

# ─── Workflow Stage Requirements ─────────────────────────────────────────────
def get_stage_requirements():
	"""Map Project shipment status to required Document Type stages (from CGM Shipping Settings)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_cgm_shipping_settings,
	)

	settings = get_cgm_shipping_settings()
	if not settings:
		return {}
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
def assign_project_reference_on_insert(doc, _method=None):
	"""Allocate Client Ref / Quantity[/ Batch] on project_name and custom_project_reference."""
	assign_lp_project_reference(doc)


def sync_project_reference_on_save(doc, _method=None):
	"""Keep project_name aligned when batch or quantity fields are edited manually."""
	refresh_project_reference_from_fields(doc)


def on_project_onload(doc, _method=None):
	"""Hydrate legacy shipment document attachments for versioned grid columns."""
	hydrate_project_ata_on_load(doc)
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		prepare_shipment_documents_for_form,
	)

	if doc.meta.has_field(SHIPMENT_DOCUMENTS_FIELD):
		prepare_shipment_documents_for_form(doc, SHIPMENT_DOCUMENTS_FIELD)


def protect_finance_cost_ledger_from_manual_edit(doc, _method=None):
	"""Billed total from journal entries is system-maintained."""
	if frappe.flags.get("cgm_syncing_finance_cost_ledger"):
		return
	if not doc.meta.has_field("custom_finance_cost_total"):
		return
	prev = doc.get_doc_before_save()
	if not prev:
		return
	if doc.get("custom_finance_cost_total") != prev.get("custom_finance_cost_total"):
		doc.set("custom_finance_cost_total", prev.get("custom_finance_cost_total"))


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
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		normalize_shipment_document_row,
		primary_attachment,
		get_draft_attachment,
	)
	from cgm_shipping.cgm_worldwide_shipping.doctype.shipment_document.shipment_document import (
		stamp_shipment_document_upload_metadata,
	)

	stamp_shipment_document_upload_metadata(doc, SHIPMENT_DOCUMENTS_FIELD)

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
		normalize_shipment_document_row(row)
		# 1. Sync the required flag from the Document Type master.
		if row.document_type:
			default_required = required_map.get(row.document_type)
			if default_required is not None:
				row.required = int(default_required)

		# 2. Auto-manage upload state (metadata stamped separately on attachment change).
		if primary_attachment(row):
			if row.status in (None, "", "Missing"):
				row.status = "Uploaded"
		elif get_draft_attachment(row) or row.get("final_attachment"):
			normalize_shipment_document_row(row)
			if primary_attachment(row) and row.status in (None, "", "Missing"):
				row.status = "Uploaded"
		else:
			row.status = "Missing"
			row.verified_by = None
			row.verified_on = None

		# 3. Sync verification metadata from status.
		if row.status in ("Verified", "Rejected"):
			if not primary_attachment(row):
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
	for code in INTAKE_DOCUMENT_CODES:
		row = find_shipment_row_for_intake_code(doc, code)
		if not intake_shipment_row_is_present(row):
			missing.append(intake_document_label(code))
	if missing:
		frappe.throw(
			f"Upload client documents in <b>Client Documents</b> first: {', '.join(missing)}. "
			"Use <b>custom_shipment_documents</b> - not Permit Register."
		)

def normalize_permit_register_rows(doc):
	"""Derive clearance phase and stamp permit attachment upload metadata."""
	if not doc.meta.has_field(PERMIT_REGISTER_FIELD):
		return
	from cgm_shipping.cgm_worldwide_shipping.doctype.permit_register.permit_register import (
		stamp_permit_register_upload_metadata,
	)

	stamp_permit_register_upload_metadata(doc, PERMIT_REGISTER_FIELD)
	for row in doc.get(PERMIT_REGISTER_FIELD) or []:
		row.clearance_phase = derive_permit_clearance_phase(row)

def derive_permit_clearance_phase(row) -> str:
	"""Map permit row finance fields to high-level clearance phase (see OPERATIONS_PROCESS.md §7)."""
	from cgm_shipping.cgm_worldwide_shipping.doctype.permit_register.permit_register import (
		permit_requires_payment,
	)

	# Foreign origin: certificate alone completes clearance (no payment path).
	if not permit_requires_payment(row) and row.get("permit_document"):
		return "Post-Cleared"

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
	for code in INTAKE_DOCUMENT_CODES:
		row = find_shipment_row_for_intake_code(project_doc, code)
		if not intake_shipment_row_is_present(row):
			return False
	return True


def project_has_verified_client_documents(project_doc) -> bool:
	"""True when every attached client document row on the project is verified."""
	docs = [
		row
		for row in get_documents(project_doc)
		if row.document_type and primary_attachment(row)
	]
	if not docs:
		return False
	return all(is_shipment_document_verified(row) for row in docs)


def project_has_client_document_files(project_doc) -> bool:
	"""True when the project shipment document table has at least one attached file."""
	return any(
		row.document_type and primary_attachment(row) for row in get_documents(project_doc)
	)


def opportunity_is_approved(opp_name: str) -> bool:
	return (
		opp_name
		and frappe.db.get_value("Opportunity", opp_name, "workflow_state")
		== APPROVED_WORKFLOW_STATE
	)


def opportunity_has_client_document_files(opp_name: str) -> bool:
	"""True when the linked Opportunity has uploaded client documents."""
	if not opp_name or not frappe.db.exists("Opportunity", opp_name):
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		get_opportunity_documents_field,
	)

	opp = frappe.get_doc("Opportunity", opp_name)
	field = get_opportunity_documents_field() or "custom_clients_documents"
	if not opp.meta.has_field(field):
		return False
	return any(
		row.document_type and primary_attachment(row)
		for row in (opp.get(field) or [])
	)


def project_ready_for_documents_received(project_doc) -> bool:
	"""True when CRM pre-shipment evidence allows the Documents Received state."""
	opp_name = project_doc.get("custom_source_opportunity")
	if opp_name:
		# Approved Opportunity = ops accepted the client file pack; branch at Documents Received.
		if opportunity_is_approved(opp_name):
			return (
				project_has_client_document_files(project_doc)
				or opportunity_has_client_document_files(opp_name)
			)
		return project_has_verified_client_documents(project_doc)
	return project_has_intake_documents(project_doc)


def cap_workflow_status_for_intake(project_doc, progress_status: str, states: list[str]) -> str:
	"""Do not advance to Documents Received (or beyond) until CI/PKL intake is satisfied."""
	if not progress_status or progress_status not in states:
		return progress_status
	if project_ready_for_documents_received(project_doc):
		return progress_status
	try:
		documents_received_index = states.index("Documents Received")
		progress_index = states.index(progress_status)
	except ValueError:
		return progress_status
	if progress_index >= documents_received_index:
		return states[0]
	return progress_status


def bootstrap_project_workflow_status(project_name: str) -> None:
	"""
	After insert: move to Documents Received when CRM already supplied verified client docs.

	Uses db.set_value to avoid Frappe's 'no transition on insert' workflow check.
	"""
	if not project_name or not frappe.db.exists("Project", project_name):
		return
	project = frappe.get_doc("Project", project_name)
	if not project.meta.has_field("custom_shipment_status"):
		return
	if project.get("custom_shipment_status") != "Draft":
		return
	if not project_ready_for_documents_received(project):
		return
	frappe.db.set_value(
		"Project",
		project_name,
		"custom_shipment_status",
		"Documents Received",
		update_modified=False,
	)


def _seed_project_workflow_state(project_name: str) -> None:
	"""Align Frappe workflow_state with custom_shipment_status after bootstrap."""
	if not project_name or not frappe.db.exists("Project", project_name):
		return
	meta = frappe.get_meta("Project")
	if not meta.has_field("workflow_state"):
		return

	shipment_status = (
		frappe.db.get_value("Project", project_name, "custom_shipment_status") or ""
	).strip()
	if not shipment_status:
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
		get_clearance_workflow_states_for_project,
	)

	project = frappe.get_doc("Project", project_name)
	valid_states = get_clearance_workflow_states_for_project(project)
	if not valid_states or shipment_status not in valid_states:
		return

	current = (frappe.db.get_value("Project", project_name, "workflow_state") or "").strip()
	if current == shipment_status:
		return

	frappe.db.set_value(
		"Project",
		project_name,
		"workflow_state",
		shipment_status,
		update_modified=False,
	)


def insert_shipment_project(project) -> str:
	"""Insert a new shipment project and apply post-insert workflow status."""
	frappe.flags.cgm_skip_task_project_sync = True
	try:
		project.insert(ignore_permissions=True)
	finally:
		frappe.flags.cgm_skip_task_project_sync = False
	refresh_project_documents(project.name)
	bootstrap_project_workflow_status(project.name)
	_seed_project_workflow_state(project.name)
	return project.name


def apply_project_tracking_defaults(project) -> None:
	"""Seed tracking sheet fields on new projects (opened date; CGM ref assigned on insert)."""
	opened_date_field = get_field_from_meta("Project", "opened_date")
	if opened_date_field and not project.get(opened_date_field):
		project.set(opened_date_field, today())

def apply_preshipment_transport_defaults(project, source_doc) -> None:
	"""Copy B/L, AWB, containers, quantity, vessel, and airline from Opportunity onto Project."""
	bl_config = get_bl_config()
	project_meta = project.meta

	apply_bill_of_lading_from_source(project, source_doc)
	copy_carrier_fields_from_source(project, source_doc)

	project_awb_field = get_project_awb_field() or "custom_air_waybill"
	source_awb_field = get_link_field_for_doctype(source_doc.doctype, "Air Waybill") or "custom_air_waybill"
	if project_meta.has_field(project_awb_field):
		awb = None
		if source_doc.meta.has_field(source_awb_field):
			awb = source_doc.get(source_awb_field)
		if not awb:
			awb = get_awb_value_from_doc(source_doc)
		if awb and not project.get(project_awb_field):
			project.set(project_awb_field, awb)

	awb_name = project.get(project_awb_field) if project_meta.has_field(project_awb_field) else None
	if awb_name and frappe.db.exists("Air Waybill", awb_name):
		apply_awb_fields_to_doc(project, frappe.get_doc("Air Waybill", awb_name))

	quantity_field = bl_config.get("opportunity_quantity_field")
	if quantity_field and project_meta.has_field(quantity_field) and not project.get(quantity_field):
		qty = source_doc.get(quantity_field)
		if qty not in (None, ""):
			project.set(quantity_field, qty)
		else:
			bl_field = bl_config.get("opportunity_bl_field")
			bl_name = project.get(bl_field) if bl_field else None
			if bl_name and frappe.db.exists("Bill of Lading", bl_name):
				project.set(
					quantity_field,
					get_bl_quantity_summary(frappe.get_doc("Bill of Lading", bl_name)),
				)
			elif awb_name and frappe.db.exists("Air Waybill", awb_name):
				project.set(
					quantity_field,
					awb_quantity_summary(frappe.get_doc("Air Waybill", awb_name)),
				)

def apply_opportunity_to_project_mappings(project, opp) -> None:
	"""Copy scalar Opportunity shipment fields onto Project when the target is empty."""
	copy_opportunity_scalars_to_project(project, opp, only_empty=True)
	copy_opportunity_requested_cargo_to_project(opp, project)


REQUESTED_CARGO_ROW_FIELDS = ("cargo_size", "quantity")


def copy_opportunity_requested_cargo_to_project(opp, project, *, replace: bool = False) -> bool:
	"""Copy FCL requested-cargo rows from Opportunity onto Project."""
	table_field = "custom_requested_cargo_quantity"
	if not (opp.meta.has_field(table_field) and project.meta.has_field(table_field)):
		return False

	new_rows = [
		{
			"cargo_size": (row.get("cargo_size") or "").strip(),
			"quantity": str(row.get("quantity") or "").strip(),
		}
		for row in opp.get(table_field) or []
	]

	existing = [
		{
			"cargo_size": (row.get("cargo_size") or "").strip(),
			"quantity": str(row.get("quantity") or "").strip(),
		}
		for row in project.get(table_field) or []
	]
	if not replace and existing:
		# Keep existing Project rows unless Opportunity has better (sized) data.
		existing_has_sizes = all(row.get("cargo_size") for row in existing) if existing else False
		new_has_sizes = all(row.get("cargo_size") for row in new_rows) if new_rows else False
		if existing_has_sizes or not new_has_sizes:
			if existing == new_rows:
				return False
			if existing_has_sizes:
				return False

	if existing == new_rows:
		return False

	project.set(table_field, [])
	for row in new_rows:
		project.append(table_field, {field: row.get(field) for field in REQUESTED_CARGO_ROW_FIELDS})
	return True


def sync_linked_project_from_booking(booking_doc, opportunity: str) -> str | None:
	"""Push Booking Confirmation cargo + documents onto the linked Project."""
	if not opportunity or not frappe.get_meta("Project").has_field("custom_source_opportunity"):
		return None

	project_name = frappe.db.get_value(
		"Project", {"custom_source_opportunity": opportunity}, "name"
	)
	if not project_name:
		return None

	frappe.has_permission("Project", ptype="write", doc=project_name, throw=True)
	project = frappe.get_doc("Project", project_name)
	opp = frappe.get_doc("Opportunity", opportunity)

	if project.meta.has_field("custom_booking_confirmation"):
		if project.get("custom_booking_confirmation") != booking_doc.name:
			project.set("custom_booking_confirmation", booking_doc.name)

	copy_opportunity_scalars_to_project(project, opp, only_empty=False)
	copy_opportunity_requested_cargo_to_project(opp, project, replace=True)
	sync_project_documents_from_opportunity(project, opp)

	project.flags.ignore_validate = True
	project.save(ignore_permissions=True)
	return project_name


def sync_linked_project_from_opportunity(opp, _method=None) -> None:
	"""Keep linked Project transport fields aligned when Opportunity intake data is filled later."""
	if getattr(opp, "is_new", lambda: False)() or not opp.name:
		return
	if not frappe.get_meta("Project").has_field("custom_source_opportunity"):
		return

	project_name = frappe.db.get_value(
		"Project", {"custom_source_opportunity": opp.name}, "name"
	)
	if not project_name:
		return

	project = frappe.get_doc("Project", project_name)
	changed = copy_opportunity_scalars_to_project(project, opp, only_empty=True)
	if copy_opportunity_requested_cargo_to_project(opp, project, replace=False):
		changed = True

	if not changed:
		return

	project.flags.ignore_validate = True
	project.save(ignore_permissions=True)


def sync_predocuments_from_source(project, source_doc) -> None:
	"""Copy Opportunity Clients Documents and Customer KRA PIN onto Project shipment documents."""
	sync_project_documents_from_opportunity(project, source_doc)


def sync_linked_project_documents_from_opportunity(opportunity: str) -> str | None:
	"""Push Opportunity client documents + Customer KRA PIN onto the linked Project."""
	if not opportunity or not frappe.get_meta("Project").has_field("custom_source_opportunity"):
		return None

	project_name = frappe.db.get_value(
		"Project", {"custom_source_opportunity": opportunity}, "name"
	)
	if not project_name:
		return None

	frappe.has_permission("Project", ptype="write", doc=project_name, throw=True)
	project = frappe.get_doc("Project", project_name)
	opp = frappe.get_doc("Opportunity", opportunity)
	sync_project_documents_from_opportunity(project, opp)

	frappe.flags.cgm_syncing_shipment_documents = True
	try:
		project.flags.ignore_validate = True
		project.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_shipment_documents = False
	return project_name

@frappe.whitelist()
def get_shipment_project_for_opportunity(opportunity: str) -> str | None:
	"""Return the shipment Project linked to an Opportunity, if any."""
	frappe.has_permission("Opportunity", ptype="read", doc=opportunity, throw=True)
	if not opportunity or not frappe.get_meta("Project").has_field("custom_source_opportunity"):
		return None
	return frappe.db.get_value(
		"Project",
		{"custom_source_opportunity": opportunity},
		"name",
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
	copy_shipment_classification_from_source(proj, opp)
	copy_tracking_fields_from_source(proj, opp)
	if proj.meta.has_field("custom_shipment_status") and not proj.get("custom_shipment_status"):
		proj.custom_shipment_status = "Draft"
	apply_project_tracking_defaults(proj)
	if project_name and not is_lp_project_reference(project_name):
		frappe.throw(
			"Projects use Client Reference / Quantity / Batch (FCL) "
			"or Client Reference / packages (LCL). "
			"Leave project_name blank to auto-generate."
		)

	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_source_opportunity"):
		proj.custom_source_opportunity = opportunity

	apply_opportunity_to_project_mappings(proj, opp)
	apply_preshipment_transport_defaults(proj, opp)
	from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment import (
		apply_project_type_from_shipment_type,
	)

	apply_project_type_from_shipment_type(proj, opp.get("custom_shipment_type"))
	sync_cargo_type_from_linked_bl(proj)
	sync_predocuments_from_source(proj, opp)
	return insert_shipment_project(proj)
