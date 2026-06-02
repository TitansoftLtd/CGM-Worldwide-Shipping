"""UCR invoice → Finance payment → Operations receipt → Finance verify → Complete."""
from __future__ import annotations

import frappe
from frappe.utils import get_url, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
	FINANCE_ROLES,
	OPERATIONS_ROLES,
	_send_task_notifications,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
	TASK_DOCUMENTS_FIELD,
	_document_type_code,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import SEA_TASK_FLOW_KEY

UCR_APPLICATION_SEQ = 3
UCR_FINANCE_SEQ = 4
UCR_DOC_CODE = "UCR_DOC"


def get_ucr_application_task(project: str) -> str | None:
	return frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": UCR_APPLICATION_SEQ,
		},
		"name",
	)


def get_ucr_finance_task(project: str) -> str | None:
	return frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": UCR_FINANCE_SEQ,
		},
		"name",
	)


def _ucr_invoice_attached(task) -> bool:
	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		if _document_type_code(row.document_type) == UCR_DOC_CODE and row.attachment:
			return True
	return False


def ucr_invoice_ready(task_name: str) -> bool:
	if not task_name or not frappe.db.exists("Task", task_name):
		return False
	if frappe.db.get_value("Task", task_name, "custom_ucr_invoice_submitted"):
		return True
	task = frappe.get_doc("Task", task_name)
	return _ucr_invoice_attached(task)


def ucr_invoice_ready_for_project(project: str) -> bool:
	task_name = get_ucr_application_task(project)
	return bool(task_name and ucr_invoice_ready(task_name))


@frappe.whitelist()
def submit_ucr_invoice_to_finance(task_name: str) -> dict:
	"""Declarant submits UCR invoice — notify Finance; task stays open until payment completes."""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != UCR_APPLICATION_SEQ:
		frappe.throw("This action is only for <b>Create UCR (IDF)</b> (task 3).")

	if not _ucr_invoice_attached(task):
		frappe.throw(
			"Attach the <b>UCR Invoice</b> on <b>Task Documents</b> "
			"(document type <b>UCR_DOC</b>) before submitting to Finance."
		)

	task.custom_ucr_invoice_submitted = 1
	task.save(ignore_permissions=True)
	sync_ucr_invoice_to_idf_record(task)

	subject = f"UCR invoice ready for review — {task.project or task.name}"
	message = (
		f"<p>The UCR invoice was submitted on task <b>{task.subject}</b> ({task.name}) "
		f"for project <b>{task.project}</b>.</p>"
		f"<p>Review the invoice on that task, then open <b>Finance pays UCR</b> "
		f"to verify, process payment, and confirm receipts.</p>"
	)
	notified = _send_task_notifications(
		task,
		subject=subject,
		message=message,
		roles=FINANCE_ROLES,
		email_template=(
			"<p>Hello,</p><p>{{ message }}</p>"
			"<p><a href=\"{{ task_url }}\">Open UCR task</a> · "
			"<a href=\"{{ project_url }}\">Open project</a></p>"
		),
	)

	finance_task = get_ucr_finance_task(task.project) if task.project else None
	return {
		"task": task.name,
		"status": task.status,
		"notified": notified,
		"finance_task": finance_task,
		"message": (
			"Finance notified. Complete this task after UCR/IDF details are recorded, "
			"then Finance will pay on the next task."
		),
	}


def notify_operations_upload_ucr_receipt(task) -> dict:
	"""After Finance records UCR payment — Operations uploads proof of payment."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != UCR_FINANCE_SEQ or not task.get("custom_payment_entry"):
		return {"notified": 0}

	subject = f"Upload UCR payment receipt — {task.project or task.name}"
	message = (
		f"<p>Payment was recorded for <b>{task.subject}</b> ({task.name}).</p>"
		f"<p>Attach the <b>UCR Payment Receipt</b> on this task as proof of payment.</p>"
	)
	return {
		"notified": _send_task_notifications(
			task,
			subject=subject,
			message=message,
			roles=OPERATIONS_ROLES,
			email_template=(
				"<p>Hello,</p><p>{{ message }}</p><p><a href=\"{{ task_url }}\">Open finance task</a></p>"
			),
		)
	}


@frappe.whitelist()
def notify_finance_verify_ucr_receipt(task_name: str) -> dict:
	if not task_name or not frappe.db.exists("Task", task_name):
		return {"notified": 0}
	task = frappe.get_doc("Task", task_name)
	return _notify_finance_verify_ucr_receipt(task)


def _notify_finance_verify_ucr_receipt(task) -> dict:
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != UCR_FINANCE_SEQ or not task.get("custom_ucr_payment_receipt"):
		return {"notified": 0}

	subject = f"Verify UCR payment receipt — {task.project or task.name}"
	message = (
		f"<p>A UCR payment receipt was uploaded for <b>{task.project}</b>.</p>"
		f"<p>Verify the receipt on task <b>{task.name}</b>, tick <b>Receipt Verified</b>, "
		f"then complete the UCR finance task.</p>"
	)
	return {
		"notified": _send_task_notifications(
			task,
			subject=subject,
			message=message,
			roles=FINANCE_ROLES,
			email_template=(
				"<p>Hello,</p><p>{{ message }}</p><p><a href=\"{{ task_url }}\">Open task</a></p>"
			),
		)
	}


def validate_ucr_application_not_manually_completed(task) -> None:
	"""Task 3 closes automatically when Finance completes the UCR payment task."""
	if frappe.flags.get("cgm_auto_completing_sea_task"):
		return
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != UCR_APPLICATION_SEQ:
		return
	frappe.throw(
		"This task cannot be marked Completed here. Attach the UCR invoice on <b>Task Documents</b>, "
		"click <b>Submit UCR invoice to Finance</b>, then complete <b>Finance pays UCR</b> "
		"after payment and receipt verification."
	)


def ucr_finance_ready_to_complete(task) -> bool:
	"""True only when the full UCR payment flow is satisfied."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != UCR_FINANCE_SEQ:
		return False
	if not ucr_invoice_ready_for_project(task.project) if task.project else False:
		return False
	if not task.get("custom_ucr_invoice_verified"):
		return False
	if not task.get("custom_purchase_invoice") or not task.get("custom_payment_entry"):
		return False
	pe_status = frappe.db.get_value("Payment Entry", task.custom_payment_entry, "docstatus")
	if int(pe_status or 0) != 1:
		return False
	if not task.get("custom_ucr_payment_receipt") or not task.get("custom_ucr_receipt_verified"):
		return False
	return True


@frappe.whitelist()
def complete_ucr_finance_task(task_name: str) -> dict:
	"""Complete Finance pays UCR only after invoice, payment, receipt, and verification."""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if int(task.get("custom_sequence_no") or 0) != UCR_FINANCE_SEQ:
		frappe.throw("This action is only for <b>Finance pays UCR</b>.")

	validate_finance_ucr_payment_task(task)
	if not ucr_finance_ready_to_complete(task):
		frappe.throw("UCR payment workflow is not finished yet.")

	task.completed_by = frappe.session.user
	task.completed_on = now_datetime()
	task.status = "Completed"
	task.save(ignore_permissions=True)
	sync_ucr_payment_to_idf_record(task)
	close_ucr_application_when_finance_done(task)
	return {"task": task.name, "status": task.status}


def validate_finance_ucr_payment_task(task) -> None:
	"""Task 4: invoice verified → PI/PE → receipt → receipt verified."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != UCR_FINANCE_SEQ:
		return

	app_task = get_ucr_application_task(task.project) if task.project else None
	if app_task and not ucr_invoice_ready(app_task):
		frappe.throw(
			"The declarant must submit the UCR invoice from <b>Create UCR (IDF)</b> first."
		)

	if not task.get("custom_ucr_invoice_verified"):
		frappe.throw(
			"Finance must tick <b>Invoice Verified</b> after reviewing the UCR invoice "
			"from the declarant task."
		)

	task_fields = frappe.get_meta("Task")
	if task_fields.has_field("custom_purchase_invoice") and not task.get("custom_purchase_invoice"):
		frappe.throw("Create and submit a <b>Purchase Invoice</b> from this task before completion.")
	if task_fields.has_field("custom_payment_entry") and not task.get("custom_payment_entry"):
		frappe.throw(
			"Record payment via <b>Make Payment</b> and submit the <b>Payment Entry</b> before completion."
		)
	if task.get("custom_payment_entry"):
		pe_status = frappe.db.get_value("Payment Entry", task.custom_payment_entry, "docstatus")
		if int(pe_status or 0) != 1:
			frappe.throw("Payment Entry must be <b>submitted</b> before completing this task.")

	if not task.get("custom_ucr_payment_receipt"):
		frappe.throw(
			"Operations must attach the <b>UCR Payment Receipt</b> on this task before completion."
		)
	if not task.get("custom_ucr_receipt_verified"):
		frappe.throw(
			"Finance must tick <b>Receipt Verified</b> after confirming the payment receipt."
		)


def enforce_ucr_finance_field_permissions(task) -> None:
	"""Role checks for UCR finance fields on task 4."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != UCR_FINANCE_SEQ or frappe.session.user == "Administrator":
		return

	roles = set(frappe.get_roles())
	is_finance = bool(set(FINANCE_ROLES) & roles)
	can_upload_receipt = bool(set(OPERATIONS_ROLES + FINANCE_ROLES) & roles)

	if task.get("custom_ucr_invoice_verified") and not is_finance:
		frappe.throw("Only <b>Finance</b> can mark <b>Invoice Verified</b>.")

	if task.get("custom_ucr_receipt_verified") and not is_finance:
		frappe.throw("Only <b>Finance</b> can mark <b>Receipt Verified</b>.")

	if task.get("custom_ucr_payment_receipt") and not can_upload_receipt:
		frappe.throw("Only <b>Operations</b> or <b>Finance</b> can attach the UCR payment receipt.")


def close_ucr_application_when_finance_done(task) -> None:
	"""When finance UCR task completes, close the declarant task if still open."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != UCR_FINANCE_SEQ or task.status != "Completed" or not task.project:
		return

	app_name = get_ucr_application_task(task.project)
	if not app_name or frappe.db.get_value("Task", app_name, "status") == "Completed":
		return

	app = frappe.get_doc("Task", app_name)
	app.status = "Completed"
	app.completed_by = task.completed_by
	app.completed_on = task.completed_on or now_datetime()
	app.description = (
		f"UCR invoice submitted to Finance; payment and receipt verification "
		f"completed on {task.name}."
	)
	frappe.flags.cgm_auto_completing_sea_task = True
	try:
		app.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_auto_completing_sea_task = False


def sync_ucr_invoice_to_idf_record(task) -> None:
	"""Mirror UCR invoice from declarant task onto Project IDF UCR Record."""
	if int(task.get("custom_sequence_no") or 0) != UCR_APPLICATION_SEQ:
		return
	if not task.project or not frappe.db.exists("DocType", "IDF UCR Record"):
		return

	invoice_url = None
	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		if _document_type_code(row.document_type) == UCR_DOC_CODE and row.attachment:
			invoice_url = row.attachment
			break
	if not invoice_url:
		return

	record_name = frappe.db.get_value("IDF UCR Record", {"project": task.project}, "name")
	if record_name:
		doc = frappe.get_doc("IDF UCR Record", record_name)
	else:
		doc = frappe.new_doc("IDF UCR Record")
		doc.project = task.project

	doc.payment_invoice = invoice_url
	if doc.payment_status in (None, "", "Pending Invoice"):
		doc.payment_status = "Invoice Submitted"
	doc.save(ignore_permissions=True)


def sync_ucr_payment_to_idf_record(task) -> None:
	"""Mirror finance UCR payment status onto IDF UCR Record."""
	if int(task.get("custom_sequence_no") or 0) != UCR_FINANCE_SEQ:
		return
	if not task.project or not frappe.db.exists("DocType", "IDF UCR Record"):
		return

	record_name = frappe.db.get_value("IDF UCR Record", {"project": task.project}, "name")
	if not record_name:
		return

	doc = frappe.get_doc("IDF UCR Record", record_name)
	if task.get("custom_ucr_invoice_verified"):
		doc.invoice_verified = 1
		doc.payment_status = "Invoice Verified"
	if task.get("custom_purchase_invoice"):
		doc.purchase_invoice = task.custom_purchase_invoice
	if task.get("custom_payment_entry"):
		doc.payment_entry = task.custom_payment_entry
		doc.payment_status = "Paid"
	if task.get("custom_ucr_payment_receipt"):
		doc.payment_receipt = task.custom_ucr_payment_receipt
		doc.payment_status = "Receipt Submitted"
	if task.get("custom_ucr_receipt_verified"):
		doc.receipt_verified = 1
		doc.payment_status = "Receipt Verified"
	if task.status == "Completed":
		doc.payment_status = "Complete"
	doc.save(ignore_permissions=True)


@frappe.whitelist()
def get_ucr_invoice_preview(task_name: str) -> dict:
	"""Return UCR invoice attachment from declarant task for Finance UI."""
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if int(task.get("custom_sequence_no") or 0) != UCR_FINANCE_SEQ:
		frappe.throw("This preview is only for the UCR finance task.")
	if not task.project:
		return {"invoice_url": None, "application_task": None}

	app_name = get_ucr_application_task(task.project)
	if not app_name:
		return {"invoice_url": None, "application_task": None}

	app = frappe.get_doc("Task", app_name)
	for row in app.get(TASK_DOCUMENTS_FIELD) or []:
		if _document_type_code(row.document_type) == UCR_DOC_CODE and row.attachment:
			return {
				"invoice_url": row.attachment,
				"application_task": app_name,
				"application_task_url": get_url(f"/app/task/{app_name}"),
			}
	return {"invoice_url": None, "application_task": app_name}
