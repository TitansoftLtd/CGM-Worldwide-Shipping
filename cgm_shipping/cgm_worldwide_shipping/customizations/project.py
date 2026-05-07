import frappe
from frappe import _
from frappe.utils import now_datetime
from pathlib import Path
import json

def get_table_field(doc):
	# Step 1: prefer plural table field.
	meta = frappe.get_meta(doc.doctype)
	if meta.has_field("custom_shipment_documents"):
		return "custom_shipment_documents"
	# Step 2: fallback to legacy singular field.
	return "custom_shipment_document"


def get_row_list(doc):
	return doc.get(get_table_field(doc)) or []


def get_stage_requirements():
	# Step 1: load workflow stage gate requirements from data file.
	path = Path(__file__).parent / "data" / "workflow_stage_requirements.json"
	if not path.exists():
		frappe.throw(_("Workflow stage requirements file is missing: {0}").format(path.name))
	data = json.loads(path.read_text())
	# Step 2: validate structure.
	if not isinstance(data, dict):
		frappe.throw(_("Workflow stage requirements must be a JSON object."))
	return data


def apply_shipment_document_automation(doc, _method=None):
	# Step 1: seed required checklist rows for selected mode.
	seed_required_document_rows(doc)
	# Step 2: normalize row status/uploader/verifier metadata.
	normalize_document_rows(doc)
	# Step 3: block workflow changes when required docs are missing.
	enforce_document_gate_on_workflow_change(doc)


def seed_required_document_rows(doc):
	# Step 1: ensure mode of transport is set before seeding.
	mode = doc.get("custom_mode_of_transport")
	if not mode:
		return
	# Step 2: identify already-added document types.
	rows = get_row_list(doc)
	existing = {r.document_type for r in rows if r.document_type}
	# Step 3: load required document types for this mode.
	doctypes = frappe.get_all(
		"Document Type",
		filters={"mode_of_transport": ["in", [mode, "", None]], "default_required": 1},
		fields=["name"],
		order_by="required_stage asc, name asc",
	)
	# Step 4: append missing required rows.
	fieldname = get_table_field(doc)
	for d in doctypes:
		if d.name not in existing:
			doc.append(fieldname, {"document_type": d.name, "required": 1, "status": "Missing"})


def normalize_document_rows(doc):
	for row in get_row_list(doc):
		# Step 1: sync `required` from Document Type master.
		if row.document_type:
			default_required = frappe.db.get_value("Document Type", row.document_type, "default_required")
			if default_required is not None:
				row.required = int(default_required)
		# Step 2: auto-manage upload state and uploader metadata.
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
		# Step 3: sync verification metadata from status.
		if row.status in ("Verified", "Rejected"):
			if not row.attachment:
				frappe.throw(f"Attach a file before marking {row.document_type or 'a document'} as {row.status}.")
			if not row.verified_by:
				row.verified_by = frappe.session.user
			if not row.verified_on:
				row.verified_on = now_datetime()
		elif row.status == "Uploaded":
			row.verified_by = None
			row.verified_on = None


def enforce_document_gate_on_workflow_change(doc):
	# Step 1: detect workflow status change.
	prev = doc.get_doc_before_save()
	if not prev:
		return
	prev_status = prev.get("custom_shipment_status")
	new_status = doc.get("custom_shipment_status")
	if not new_status or new_status == prev_status:
		return
	# Step 2: determine document stages required for target status.
	stage_requirements = get_stage_requirements()
	required_stages = stage_requirements.get(new_status)
	if not required_stages:
		return
	# Step 3: gather missing required docs for those stages.
	missing = []
	for row in get_row_list(doc):
		if not row.document_type or not row.required:
			continue
		stage = frappe.db.get_value("Document Type", row.document_type, "required_stage")
		if stage not in required_stages:
			continue
		if not row.attachment or row.status != "Verified":
			missing.append(row.document_type)
	# Step 4: stop workflow move when evidence is incomplete.
	if missing:
		frappe.throw(
			_(
				"Cannot move shipment to <b>{0}</b>. Verify required documents first: {1}"
			).format(new_status, ", ".join(sorted(set(missing))))
		)


