import frappe
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	SEA_TASK_FLOW_KEY,
	SHIPMENT_DOCUMENTS_FIELD,
	sync_linked_attachments_to_project,
)


# ─── Shipment Document Table ──────────────────────────────────────────────────


def get_shipment_documents(doc):
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


def apply_shipment_document_automation(doc, _method=None):
	# 1. Seed required checklist rows for the selected mode of transport.
	seed_required_document_rows(doc)
	# 2. Pull files from linked Lead, Customer, and Tasks into shipment documents.
	if not frappe.flags.get("cgm_syncing_shipment_documents"):
		sync_linked_attachments_to_project(doc)
	# 3. Normalise row status and uploader/verifier metadata.
	normalize_document_rows(doc)
	# 4. Block workflow changes when required documents are missing.
	enforce_document_gate_on_workflow_change(doc)
	# 5. Sea only: IDF Created requires sea task plan and Task 1 completed.
	enforce_sea_task_gate_on_workflow_change(doc)


def seed_required_document_rows(doc):
	# 1. Skip when mode of transport is not set.
	mode = doc.get("custom_mode_of_transport")
	if not mode:
		return

	# 2. Collect document types already on the project.
	rows = get_shipment_documents(doc)
	existing = {r.document_type for r in rows if r.document_type}

	# 3. Load required Document Types for this mode.
	doctypes = frappe.get_all(
		"Document Type",
		filters={"mode_of_transport": ["in", [mode, "", None]], "default_required": 1},
		fields=["name"],
		order_by="required_stage asc, name asc",
	)

	# 4. Append any missing required rows.
	for d in doctypes:
		if d.name not in existing:
			doc.append(
				SHIPMENT_DOCUMENTS_FIELD,
				{"document_type": d.name, "required": 1, "status": "Missing"},
			)


def normalize_document_rows(doc):
	for row in get_shipment_documents(doc):
		# 1. Sync the required flag from the Document Type master.
		if row.document_type:
			default_required = frappe.db.get_value("Document Type", row.document_type, "default_required")
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
	missing = []
	for row in get_shipment_documents(doc):
		if not row.document_type or not row.required:
			continue
		stage = frappe.db.get_value("Document Type", row.document_type, "required_stage")
		if stage not in required_stages:
			continue
		if not row.attachment or row.status != "Verified":
			missing.append(row.document_type)

	# 4. Stop the workflow move when evidence is incomplete.
	if missing:
		labels = ", ".join(sorted(set(missing)))
		frappe.throw(f"Cannot move shipment to <b>{new_status}</b>. Verify required documents first: {labels}")


def enforce_sea_task_gate_on_workflow_change(doc):
	"""Sea import only: entering IDF Created requires Task 1 of the sea template to be Completed."""
	# 1. Detect a shipment status change into IDF Created.
	prev = doc.get_doc_before_save()
	if not prev:
		return
	prev_status = prev.get("custom_shipment_status")
	new_status = doc.get("custom_shipment_status")
	if not new_status or new_status == prev_status:
		return
	if new_status != "IDF Created":
		return
	if doc.get("custom_mode_of_transport") != "Sea":
		return

	project_fields = frappe.get_meta(doc.doctype)
	if not project_fields.has_field("custom_mode_of_transport"):
		return

	# 2. Look up sea import Task 1 on this project.
	task = frappe.db.get_value(
		"Task",
		{
			"project": doc.name,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": 1,
		},
		["name", "subject", "status"],
		as_dict=True,
	)
	if not task:
		frappe.throw(
			"Cannot move to <b>IDF Created</b> yet. Generate the <b>Sea Task Plan</b> on this project first, "
			"then complete Task 1 (Create UCR and IDF, then hand off for payment)."
		)
	if task.status != "Completed":
		status = task.status or "unset"
		frappe.throw(
			f"Cannot move to <b>IDF Created</b> until sea Task 1 is <b>Completed</b> "
			f"(Declarant: UCR/IDF in portal, attach proofs on the task; Finance: payment from the same task). "
			f"Task <b>{task.name}</b> is currently <b>{status}</b>."
		)
