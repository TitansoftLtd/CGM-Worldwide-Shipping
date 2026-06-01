"""Task hooks — sync documents to Project; enforce completion rules."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
	SEA_AUTO_COMPLETE_TASK_SEQS,
	SEA_TASK_FLOW_KEY,
	get_incomplete_sea_tasks,
	sync_project_shipment_status_from_tasks,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
	apply_finance_payment_to_project_permits,
	seed_required_task_document_rows,
	sync_task_permits_to_project,
	validate_sea_task_can_complete,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	refresh_project_shipment_documents,
)


def before_task_save(doc, _method=None):
	"""Pre-fill required document rows while the task is still open."""
	if doc.get("custom_task_flow_key") != SEA_TASK_FLOW_KEY:
		return
	if doc.status in ("Completed", "Cancelled"):
		return
	seed_required_task_document_rows(doc)
	from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
		enforce_receipt_verified_permission,
		seed_finance_task_permits_from_project,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
		enforce_ucr_finance_field_permissions,
		sync_ucr_payment_to_idf_record,
	)

	seed_finance_task_permits_from_project(doc)
	enforce_receipt_verified_permission(doc)
	enforce_ucr_finance_field_permissions(doc)
	if doc.status != "Cancelled":
		sync_ucr_payment_to_idf_record(doc)


def on_task_update(doc, _method=None):
	if doc.get("project"):
		refresh_project_shipment_documents(doc.project)
		sync_task_permits_to_project(doc)
		if doc.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY:
			sync_project_shipment_status_from_tasks(doc.project)
	if doc.status == "Completed":
		apply_finance_payment_to_project_permits(doc)
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			close_permit_application_when_finance_done,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
			close_ucr_application_when_finance_done,
		)

		close_permit_application_when_finance_done(doc)
		close_ucr_application_when_finance_done(doc)


def validate_task_completion_requirements(doc, _method=None):
	"""Task → Completed only when documents, permits, and payments are satisfied."""
	prev = doc.get_doc_before_save()
	if doc.status != "Completed":
		return
	if prev and prev.status == "Completed":
		return

	seq = int(doc.get("custom_sequence_no") or 0)
	if (
		doc.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY
		and seq in SEA_AUTO_COMPLETE_TASK_SEQS
		and frappe.flags.get("cgm_auto_completing_sea_task")
	):
		return

	if (
		doc.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY
		and seq in SEA_AUTO_COMPLETE_TASK_SEQS
	):
		return

	if doc.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY:
		if seq > 1:
			incomplete = get_incomplete_sea_tasks(doc.project, seq)
			if incomplete:
				prev_task = incomplete[0]
				frappe.throw(
					f"Complete prior sea tasks in order first. Next open: "
					f"<b>Task {prev_task.seq}: {prev_task.subject}</b> ({prev_task.status or 'Open'})."
				)
		validate_sea_task_can_complete(doc)
