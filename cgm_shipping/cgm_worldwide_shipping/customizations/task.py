"""Task hooks - sync documents to Project; enforce completion rules."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
	SEA_TASK_FLOW_KEY,
	get_incomplete_sea_tasks,
	sync_project_shipment_status_from_tasks,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
	is_auto_complete_task,
	is_permit_application_task,
	is_permit_finance_payment_task,
	is_ucr_application_task,
	is_ucr_finance_payment_task,
	is_ucr_workflow_task,
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


def _sea_task_seq(doc) -> int:
	return int(doc.get("custom_sequence_no") or 0)


def _is_sea_task(doc) -> bool:
	return doc.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY


def on_task_onload(doc, _method=None):
	"""Remove orphan UCR Invoice rows from DB before the form is shown (link validation runs before before_save)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
		prepare_ucr_task_tables,
		purge_invoice_rows_from_task_documents_db,
	)

	if doc.is_new():
		return
	if purge_invoice_rows_from_task_documents_db(doc.name):
		doc.reload()
		if _is_sea_task(doc):
			prepare_ucr_task_tables(doc)
	if _is_sea_task(doc) and is_ucr_workflow_task(_sea_task_seq(doc)):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
			ensure_ucr_finance_lines_saved,
			sync_ucr_status_from_finance_to_application,
		)

		changed = ensure_ucr_finance_lines_saved(doc)
		seq = _sea_task_seq(doc)
		if is_ucr_application_task(seq):
			changed = sync_ucr_status_from_finance_to_application(doc) or changed
			if doc.status not in ("Completed", "Cancelled"):
				from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
					try_auto_complete_ucr_application_task,
				)

				if try_auto_complete_ucr_application_task(doc):
					changed = True
		elif is_ucr_finance_payment_task(seq) and doc.status not in ("Completed", "Cancelled"):
			if doc.project:
				from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
					copy_ucr_receipt_to_finance_task,
				)
				from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
					get_ucr_application_task,
					try_auto_complete_ucr_finance_task,
				)

				app_name = get_ucr_application_task(doc.project)
				if app_name:
					copy_ucr_receipt_to_finance_task(frappe.get_doc("Task", app_name))
					doc.reload()
				if try_auto_complete_ucr_finance_task(doc):
					changed = True
		if changed:
			doc.reload()

	if _is_sea_task(doc) and is_permit_finance_payment_task(_sea_task_seq(doc)):
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			ensure_finance_permit_rows_saved,
		)

		if ensure_finance_permit_rows_saved(doc):
			doc.reload()

	if _is_sea_task(doc) and is_permit_application_task(_sea_task_seq(doc)):
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			merge_project_permits_into_application_task,
		)

		if merge_project_permits_into_application_task(doc):
			doc.reload()


def before_task_save(doc, _method=None):
	"""Pre-fill required document rows while the task is still open."""
	if not _is_sea_task(doc):
		return
	if doc.status in ("Completed", "Cancelled"):
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
		enforce_receipt_verified_permission,
		seed_finance_task_permits_from_project,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
		migrate_invoice_attachments_from_documents,
		normalize_finance_line_verification,
		prepare_ucr_task_tables,
	)

	migrate_invoice_attachments_from_documents(doc)
	prepare_ucr_task_tables(doc)
	seed_required_task_document_rows(doc)
	from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
		enforce_ucr_finance_field_permissions,
		sync_ucr_payment_to_idf_record,
	)

	seed_finance_task_permits_from_project(doc)
	normalize_finance_line_verification(doc)
	enforce_receipt_verified_permission(doc)
	enforce_ucr_finance_field_permissions(doc)
	if doc.status != "Cancelled":
		sync_ucr_payment_to_idf_record(doc)


def on_task_update(doc, _method=None):
	seq = _sea_task_seq(doc)
	if _is_sea_task(doc) and is_ucr_application_task(seq) and doc.status not in (
		"Completed",
		"Cancelled",
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
			handle_ucr_application_receipt_upload,
		)

		handle_ucr_application_receipt_upload(doc)
		from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
			try_auto_complete_ucr_application_task,
		)

		try_auto_complete_ucr_application_task(doc)

	if (
		_is_sea_task(doc)
		and is_ucr_finance_payment_task(seq)
		and doc.status not in ("Completed", "Cancelled")
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
			try_auto_complete_ucr_finance_task,
		)

		try_auto_complete_ucr_finance_task(doc)

	if (
		_is_sea_task(doc)
		and is_permit_finance_payment_task(seq)
		and doc.status not in ("Completed", "Cancelled")
		and not frappe.flags.get("cgm_permit_finance_completing")
	):
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			try_auto_complete_permit_finance_task,
		)

		try_auto_complete_permit_finance_task(doc)

	if frappe.flags.get("cgm_skip_task_project_sync"):
		return
	if doc.get("project"):
		refresh_project_shipment_documents(doc.project)
		sync_task_permits_to_project(doc)
		if _is_sea_task(doc):
			if is_permit_application_task(seq):
				from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
					get_permit_finance_task,
					sync_permit_invoices_to_finance_task,
				)

				fin_name = get_permit_finance_task(doc.project, seq)
				if fin_name and not frappe.flags.get("cgm_permit_finance_completing"):
					sync_permit_invoices_to_finance_task(
						frappe.get_doc("Task", fin_name), save=True
					)
			sync_project_shipment_status_from_tasks(doc.project)
	prev = doc.get_doc_before_save()
	if doc.status == "Completed" and (not prev or prev.status != "Completed"):
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

	seq = _sea_task_seq(doc)
	if (
		_is_sea_task(doc)
		and frappe.flags.get("cgm_auto_completing_sea_task")
		and (
			is_auto_complete_task(seq)
			or is_ucr_application_task(seq)
			or is_ucr_finance_payment_task(seq)
		)
	):
		return

	if _is_sea_task(doc) and is_auto_complete_task(seq):
		return

	if _is_sea_task(doc):
		if seq > 1:
			incomplete = get_incomplete_sea_tasks(doc.project, seq)
			if incomplete:
				prev_task = incomplete[0]
				frappe.throw(
					f"Complete prior sea tasks in order first. Next open: "
					f"<b>Task {prev_task.seq}: {prev_task.subject}</b> ({prev_task.status or 'Open'})."
				)
		validate_sea_task_can_complete(doc)
