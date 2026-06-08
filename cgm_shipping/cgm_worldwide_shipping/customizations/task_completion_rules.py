"""
Sea task completion rules - driven by CGM Shipping Settings where possible.

Task level: invoices/receipts on Task Finance Lines; clearance docs on Task Documents; permits on Task Permits.
Project level: custom_permit_register synced from Task permits (see sync_task_permits_to_project).
"""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY
from cgm_shipping.cgm_worldwide_shipping.customizations.documents.service import (
	TASK_DOCUMENTS_FIELD,
	get_document_type_link_name,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
	PERMIT_REGISTER_FIELD,
	derive_permit_clearance_phase,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.service import (
	SUPPLIER_INVOICE_CODE,
	get_permit_stage_for_sequence,
	get_required_document_codes,
	is_auto_complete_task,
	is_finance_payment_task,
	is_light_proof_task,
	is_permit_application_task,
	is_permit_finance_payment_task,
	is_ucr_application_task,
	is_ucr_finance_payment_task,
)

TASK_PERMITS_FIELD = "custom_task_permits"

TASK_DOCUMENT_TYPE_DEFAULTS: dict[str, dict] = {
	"SUP_INV": {
		"category": "Finance",
		"required_stage": "IDF & UCR",
		"default_required": 0,
	},
	"IDF_CERT": {
		"category": "Customs",
		"required_stage": "IDF & UCR",
		"default_required": 0,
	},
	"INSPECT": {
		"category": "Compliance",
		"required_stage": "Client inspection",
		"default_required": 0,
	},
	"MANIFEST": {
		"category": "Customs",
		"required_stage": "Arrival & manifest",
		"default_required": 0,
	},
	"ENTRY": {
		"category": "Customs",
		"required_stage": "Customs entry & taxes",
		"default_required": 0,
	},
	"DO": {
		"category": "Customs",
		"required_stage": "Port & line (DO / charges)",
		"default_required": 0,
	},
	"FIELD": {
		"category": "Compliance",
		"required_stage": "Field clearance & release",
		"default_required": 0,
	},
	"BL": {
		"category": "Transport",
		"required_stage": "Arrival & manifest",
		"default_required": 0,
	},
}


def ensure_task_document_types() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents.service import (
		DOCUMENT_TYPE_DEFAULTS,
		ensure_document_types,
	)

	ensure_document_types()
	for code, defaults in TASK_DOCUMENT_TYPE_DEFAULTS.items():
		if get_document_type_link_name(code):
			continue
		doc = frappe.new_doc("Document Type")
		doc.code = code
		for key, value in defaults.items():
			setattr(doc, key, value)
		doc.insert(ignore_permissions=True)
		if doc.meta.is_submittable and doc.docstatus == 0:
			doc.submit()


def get_document_type_code(document_type_link: str | None) -> str | None:
	if not document_type_link:
		return None
	return frappe.db.get_value("Document Type", document_type_link, "code")


def attached_document_codes(task) -> set[str]:
	codes = set()
	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		code = get_document_type_code(row.document_type)
		if code and row.attachment:
			codes.add(code)
	return codes


def seed_required_task_document_rows(task) -> None:
	if not task.meta.has_field(TASK_DOCUMENTS_FIELD):
		return
	seq = int(task.get("custom_sequence_no") or 0)
	if is_ucr_application_task(seq):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
			ensure_idf_certificate_document_row,
		)

		ensure_idf_certificate_document_row(task)
		return

	required = get_required_document_codes(seq)
	if not required:
		return

	existing_types = {row.document_type for row in task.get(TASK_DOCUMENTS_FIELD) or [] if row.document_type}
	for code in required:
		dt_name = get_document_type_link_name(code)
		if not dt_name or dt_name in existing_types:
			continue
		task.append(
			TASK_DOCUMENTS_FIELD,
			{"document_type": dt_name, "status": "Missing"},
		)
		existing_types.add(dt_name)


def validate_sea_task_can_complete(task) -> None:
	if task.get("custom_task_flow_key") != SEA_TASK_FLOW_KEY:
		return
	if frappe.flags.get("cgm_auto_completing_sea_task"):
		return

	seq = int(task.get("custom_sequence_no") or 0)
	if is_auto_complete_task(seq):
		return

	seed_required_task_document_rows(task)

	if is_permit_application_task(seq):
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			validate_permit_application_can_complete,
		)

		validate_permit_application_task(task, seq)
		validate_permit_application_can_complete(task)
	elif is_ucr_application_task(seq):
		from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
			validate_ucr_application_not_manually_completed,
		)

		validate_ucr_application_not_manually_completed(task)
	elif is_light_proof_task(seq):
		validate_light_proof_task(task)
	elif not is_finance_payment_task(seq):
		validate_required_documents(task, seq)

	if is_finance_payment_task(seq):
		if is_ucr_finance_payment_task(seq):
			from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
				validate_finance_ucr_payment_task,
			)

			validate_finance_ucr_payment_task(task)
		else:
			validate_finance_task(task)
			if is_permit_finance_payment_task(seq):
				from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
					validate_finance_permit_payment_task,
				)

				validate_finance_permit_payment_task(task)


def validate_required_documents(task, seq: int) -> None:
	required_codes = get_required_document_codes(seq)
	if not required_codes:
		return

	attached = attached_document_codes(task)
	missing = []
	for code in required_codes:
		if code not in attached:
			label = frappe.db.get_value("Document Type", {"code": code}, "name") or code
			missing.append(label)

	if missing:
		frappe.throw(
			"Attach required documents on <b>Task Documents</b> before completing this task: "
			f"<b>{', '.join(missing)}</b>."
		)

	empty_rows = [
		row.document_type or "Document"
		for row in task.get(TASK_DOCUMENTS_FIELD) or []
		if row.document_type and not row.attachment
	]
	if empty_rows:
		frappe.throw(
			"Remove empty document rows or upload attachments for: "
			f"<b>{', '.join(empty_rows)}</b>."
		)


def validate_light_proof_task(task) -> None:
	has_doc = bool(attached_document_codes(task))
	has_text = bool((task.description or "").strip())
	has_ref = bool((task.get("custom_external_ref_no") or "").strip())
	if not (has_doc or has_text or has_ref):
		frappe.throw(
			"Add a task document, <b>Description</b>, or <b>External Ref No</b> before completing this step."
		)


def validate_permit_application_task(task, seq: int) -> None:
	if not task.meta.has_field(TASK_PERMITS_FIELD):
		frappe.throw("Task Permits table is not available on this site. Run <b>bench migrate</b>.")

	rows = task.get(TASK_PERMITS_FIELD) or []
	if not rows:
		frappe.throw(
			"Add at least one permit on <b>Task Permits</b> (e.g. DVS, NBA, VMD, ACA, SCA) "
			"and attach the <b>Permit Invoice</b> for each before completing this task."
		)

	missing = []
	for row in rows:
		label = row.permit_type or "Permit"
		if not row.permit_type:
			missing.append("Permit type (select DVS / NBA / VMD / ACA / SCA)")
			continue
		if not row.get("payment_invoice"):
			missing.append(f"{label} - supplier/permit invoice")

	if missing:
		frappe.throw(
			"Complete <b>Task Permits</b> before finishing this task:<ul>"
			+ "".join(f"<li>{m}</li>" for m in missing)
			+ "</ul>",
			title="Permit documents required",
		)


def validate_finance_task(task) -> None:
	seq = int(task.get("custom_sequence_no") or 0)
	attached = attached_document_codes(task)
	if not is_permit_finance_payment_task(seq) and SUPPLIER_INVOICE_CODE not in attached:
		frappe.throw(
			"Attach the <b>Supplier Invoice</b> on <b>Task Documents</b> for Accounts to verify "
			"before completing this finance task."
		)

	task_fields = frappe.get_meta("Task")
	if task_fields.has_field("custom_purchase_invoice") and not task.get("custom_purchase_invoice"):
		frappe.throw(
			"Create and submit a <b>Purchase Invoice</b> from this task before completion."
		)
	if task_fields.has_field("custom_payment_entry") and not task.get("custom_payment_entry"):
		frappe.throw(
			"Record payment via <b>Make Payment</b> and submit the <b>Payment Entry</b> before completion."
		)
	if task.get("custom_payment_entry"):
		pe_status = frappe.db.get_value("Payment Entry", task.custom_payment_entry, "docstatus")
		if int(pe_status or 0) != 1:
			frappe.throw("Payment Entry must be <b>submitted</b> before completing this finance task.")


def sync_task_permits_to_project(task) -> None:
	if frappe.flags.get("cgm_syncing_permits"):
		return
	if not task.get("project") or not task.meta.has_field(TASK_PERMITS_FIELD):
		return
	rows = task.get(TASK_PERMITS_FIELD) or []
	if not rows:
		return

	if not frappe.db.exists("Project", task.project):
		return

	project = frappe.get_doc("Project", task.project)
	if not project.meta.has_field(PERMIT_REGISTER_FIELD):
		return

	seq = int(task.get("custom_sequence_no") or 0)
	default_stage = get_permit_stage_for_sequence(seq)
	is_finance_permit_payment = is_permit_finance_payment_task(seq)

	by_type: dict[str, object] = {
		r.permit_type: r for r in project.get(PERMIT_REGISTER_FIELD) or [] if r.permit_type
	}

	for trow in rows:
		if not trow.permit_type:
			continue
		prow = by_type.get(trow.permit_type)
		if not prow:
			prow = project.append(PERMIT_REGISTER_FIELD, {})
			by_type[trow.permit_type] = prow

		prow.permit_type = trow.permit_type
		prow.stage = trow.stage or default_stage
		if trow.get("payment_invoice"):
			prow.payment_invoice = trow.payment_invoice
			prow.status = "Invoice Submitted"
			if trow.get("invoice_amount"):
				prow.invoice_amount = trow.invoice_amount
		if trow.get("permit_document"):
			prow.permit_document = trow.permit_document
		if trow.get("payment_receipt"):
			prow.payment_receipt = trow.payment_receipt
			prow.status = prow.status or "Receipt Submitted"

		if is_finance_permit_payment and task.get("custom_purchase_invoice"):
			prow.purchase_invoice = task.custom_purchase_invoice
			prow.invoice_verified = 1
			prow.status = "Invoice Verified"
		if is_finance_permit_payment and task.get("custom_payment_entry"):
			prow.payment_entry = task.custom_payment_entry
			prow.payment_date = frappe.db.get_value(
				"Payment Entry", task.custom_payment_entry, "posting_date"
			)
			prow.status = "Paid"
		if is_finance_permit_payment and trow.get("receipt_verified"):
			prow.receipt_verified = trow.receipt_verified

		if hasattr(prow, "custom_source_task"):
			prow.custom_source_task = task.name
		prow.clearance_phase = derive_permit_clearance_phase(prow)

	frappe.flags.cgm_syncing_permits = True
	try:
		project.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_syncing_permits = False


def apply_finance_payment_to_project_permits(task) -> None:
	if not is_permit_finance_payment_task(int(task.get("custom_sequence_no") or 0)):
		return
	sync_task_permits_to_project(task)


@frappe.whitelist()
def reopen_task_for_permit_attachments(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_permit_application_task(seq):
		frappe.throw("This action is only for pre-/post-clearance permit application tasks.")

	missing = [r.permit_type for r in task.get(TASK_PERMITS_FIELD) or [] if not r.get("payment_invoice")]
	if not missing and task.status != "Completed":
		frappe.throw("Task is already open, or all permit rows already have invoices attached.")

	task.status = "Open"
	task.progress = 0
	task.completed_by = None
	task.completed_on = None
	task.save(ignore_permissions=True)
	sync_task_permits_to_project(task)
	return {"task": task.name, "status": task.status, "missing_invoices": missing}


@frappe.whitelist()
def get_project_permit_invoices(project: str) -> list[dict]:
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	if not frappe.db.exists("Project", project):
		frappe.throw("Project not found.")
	project_doc = frappe.get_doc("Project", project)
	return [
		{
			"permit_type": r.permit_type,
			"payment_invoice": r.get("payment_invoice"),
			"invoice_amount": r.get("invoice_amount"),
			"clearance_phase": r.get("clearance_phase"),
			"status": r.get("status"),
			"name": r.name,
		}
		for r in project_doc.get(PERMIT_REGISTER_FIELD) or []
	]


# Backward-compatible alias for patches and finance modules.
attached_codes = attached_document_codes


@frappe.whitelist()
def get_task_completion_hint(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	seq = int(task.get("custom_sequence_no") or 0)
	return {
		"sequence_no": seq,
		"requires_supplier_invoice": is_finance_payment_task(seq)
		and not is_permit_finance_payment_task(seq),
		"requires_permits": is_permit_application_task(seq),
		"required_doc_codes": get_required_document_codes(seq),
	}
