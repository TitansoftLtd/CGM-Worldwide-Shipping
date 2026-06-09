"""UCR invoice → Finance payment → Declarant receipt → Finance verify → Complete."""
from __future__ import annotations

from collections.abc import Callable

import frappe
from frappe.utils import get_url, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications_service import (
	UCR_INVOICE_TO_FINANCE,
	UCR_RECEIPT_FOR_DECLARANT,
	UCR_RECEIPT_VERIFY_FINANCE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications_service import (
	send_notification,
	workflow_notify_message,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.permissions_service import (
	user_has_finance_department_access,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
	TASK_FINANCE_FIELD,
	get_ucr_invoice_line,
	get_ucr_receipt_line,
	prepare_ucr_task_tables,
	seed_ucr_finance_lines,
	sync_idf_certificate_to_project,
	sync_ucr_finance_lines_to_idf_record,
	ucr_invoice_attached,
	ucr_invoice_verified,
	ucr_receipt_attached,
	ucr_receipt_verified,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
	get_ucr_create_sequence,
	get_ucr_payment_sequence,
	is_ucr_application_task,
	is_ucr_finance_payment_task,
)
# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

FINANCE_AUDIENCE = "Finance"
DECLARANT_AUDIENCE = "Declarant"


# ------------------------------------------------------------------
# Task lookups
# ------------------------------------------------------------------


def task_sequence(task) -> int:
	return int(task.get("custom_sequence_no") or 0)


def get_task_name_by_sequence(project: str, sequence_no: int) -> str | None:
	if not project or not sequence_no:
		return None
	return frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": sequence_no,
		},
		"name",
	)


def get_ucr_task(project: str, task_type: str) -> str | None:
	seq_by_type = {
		"create": get_ucr_create_sequence(),
		"payment": get_ucr_payment_sequence(),
	}
	seq = seq_by_type.get(task_type)
	if not seq:
		return None
	return get_task_name_by_sequence(project, seq)


def get_ucr_create_task(project: str) -> str | None:
	return get_ucr_task(project, "create")


def get_ucr_payment_task(project: str) -> str | None:
	return get_ucr_task(project, "payment")


def is_ucr_create_task(task) -> bool:
	return is_ucr_application_task(task_sequence(task))


def is_ucr_payment_task_doc(task) -> bool:
	return is_ucr_finance_payment_task(task_sequence(task))


# ------------------------------------------------------------------
# UCR document state
# ------------------------------------------------------------------


def ucr_invoice_attached_legacy(task) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
		TASK_DOCUMENTS_FIELD,
		get_document_type_code,
	)

	legacy = frozenset({"UCR_DOC", "UCR_INV", "UCR Invoice"})
	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		code = get_document_type_code(row.document_type)
		if code in legacy and row.attachment:
			return True
	return False


def ucr_invoice_submitted(task_name: str) -> bool:
	if not task_name or not frappe.db.exists("Task", task_name):
		return False
	if (
		frappe.get_meta("Task").has_field("custom_ucr_invoice_submitted")
		and frappe.db.get_value("Task", task_name, "custom_ucr_invoice_submitted")
	):
		return True
	task = frappe.get_doc("Task", task_name)
	if task.meta.has_field(TASK_FINANCE_FIELD):
		return ucr_invoice_attached(task)
	return ucr_invoice_attached_legacy(task)


def project_has_submitted_ucr_invoice(project: str) -> bool:
	task_name = get_ucr_create_task(project)
	return bool(task_name and ucr_invoice_submitted(task_name))


def idf_certificate_uploaded(task) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
		get_document_type_code,
	)

	for row in task.get("custom_task_documents") or []:
		if get_document_type_code(row.document_type) == "IDF_CERT" and row.attachment:
			return True
	return False


def ucr_invoice_verified_for_create_task(task, finance_task=None) -> bool:
	if task.get("custom_ucr_invoice_verified"):
		return True
	if ucr_invoice_verified(task):
		return True
	if finance_task is None and task.project:
		finance_name = get_ucr_payment_task(task.project)
		finance_task = frappe.get_doc("Task", finance_name) if finance_name else None
	if finance_task:
		fin_inv = get_ucr_invoice_line(finance_task)
		if fin_inv and fin_inv.verified:
			return True
	return False


def ucr_receipt_attached_for_payment_workflow(task) -> bool:
	if ucr_receipt_attached(task) or task.get("custom_ucr_payment_receipt"):
		return True
	if not task.project:
		return False
	app_name = get_ucr_create_task(task.project)
	if not app_name:
		return False
	app = frappe.get_doc("Task", app_name)
	return ucr_receipt_attached(app)


def can_complete_ucr_create_task(task, finance_task=None) -> bool:
	if not is_ucr_create_task(task):
		return False
	if not ucr_invoice_attached(task) and not task.get("custom_ucr_invoice_submitted"):
		return False
	if not ucr_invoice_verified_for_create_task(task, finance_task):
		return False
	if not ucr_receipt_attached(task):
		return False
	return idf_certificate_uploaded(task)


def can_complete_ucr_payment_task(task) -> bool:
	if not is_ucr_payment_task_doc(task):
		return False
	if task.project and not project_has_submitted_ucr_invoice(task.project):
		return False

	inv_ok = ucr_invoice_verified(task) or task.get("custom_ucr_invoice_verified")
	if not inv_ok:
		return False

	rec_ok = ucr_receipt_verified(task) or task.get("custom_ucr_receipt_verified")
	if not rec_ok:
		return False
	return ucr_receipt_attached_for_payment_workflow(task)


# ------------------------------------------------------------------
# Sync / project hooks
# ------------------------------------------------------------------


def run_project_refresh_hooks(project: str) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
		sync_project_shipment_status_from_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		refresh_project_shipment_documents,
	)

	refresh_project_shipment_documents(project)
	sync_project_shipment_status_from_tasks(project)


def sync_ucr_payment_to_idf_record(task) -> None:
	sync_ucr_finance_lines_to_idf_record(task)
	seq = task_sequence(task)
	if is_ucr_payment_task_doc(task) and not frappe.flags.get("cgm_syncing_ucr_receipt"):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
			sync_ucr_receipt_verification_to_application_task,
			sync_ucr_verification_to_application_task,
		)

		sync_ucr_verification_to_application_task(task)
		sync_ucr_receipt_verification_to_application_task(task)
	if is_ucr_create_task(task) or is_ucr_payment_task_doc(task):
		sync_idf_certificate_to_project(task)


def sync_ucr_invoice_to_finance_task(project: str) -> str | None:
	finance_name = get_ucr_payment_task(project)
	if not finance_name:
		return None

	finance_task = frappe.get_doc("Task", finance_name)
	prepare_ucr_task_tables(finance_task)
	finance_task.flags.ignore_links = True
	try:
		finance_task.save(ignore_permissions=True)
	finally:
		finance_task.flags.ignore_links = False
	return finance_name


# ------------------------------------------------------------------
# Notifications
# ------------------------------------------------------------------


@frappe.whitelist()
def submit_ucr_invoice_to_finance(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_create_task(task):
		frappe.throw("This action is only for <b>Create UCR (IDF)</b> (task 3).")

	seed_ucr_finance_lines(task)
	if not ucr_invoice_attached(task) and not ucr_invoice_attached_legacy(task):
		frappe.throw(
			"Attach the <b>UCR Invoice</b> on <b>Invoices & Receipts</b> before submitting to Finance."
		)

	if task.meta.has_field("custom_ucr_invoice_submitted"):
		task.custom_ucr_invoice_submitted = 1
	task.save(ignore_permissions=True)
	sync_ucr_finance_lines_to_idf_record(task)

	if not task.project:
		frappe.throw("This task is not linked to a project.")

	finance_task_name = sync_ucr_invoice_to_finance_task(task.project)
	if not finance_task_name:
		frappe.throw(
			"Could not find <b>Finance pays UCR</b> on this project. Regenerate the sea task plan."
		)

	finance_task = frappe.get_doc("Task", finance_task_name)
	fin_inv = get_ucr_invoice_line(finance_task)

	notify_result = send_notification(
		UCR_INVOICE_TO_FINANCE,
		finance_task,
		audience=FINANCE_AUDIENCE,
	)

	return {
		"task": task.name,
		"status": task.status,
		"finance_task": finance_task_name,
		"finance_task_url": get_url(f"/app/task/{finance_task_name}"),
		**notify_result,
		"message": workflow_notify_message(
			"Finance notified on <b>Finance pays UCR</b>. Declarant: upload the IDF/UCR certificate "
			"under <b>Clearance Documents</b> on Create UCR (IDF) when it is issued.",
			notify_result,
			audience=FINANCE_AUDIENCE,
		),
	}


def notify_declarant_upload_ucr_receipt(task) -> dict:
	if not is_ucr_payment_task_doc(task):
		return {"notified": 0}
	if not task.get("custom_payment_entry") or not task.project:
		return {"notified": 0}

	app_name = get_ucr_create_task(task.project)
	if not app_name:
		return {"notified": 0}

	app = frappe.get_doc("Task", app_name)
	seed_ucr_finance_lines(app)
	try:
		app.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="UCR receipt seeding failed",
			message=f"Could not seed UCR finance lines on {app_name}: {frappe.get_traceback()}",
		)

	result = send_notification(
		UCR_RECEIPT_FOR_DECLARANT,
		app,
		audience=DECLARANT_AUDIENCE,
	)
	return {
		**result,
		"application_task": app_name,
		"application_task_url": get_url(f"/app/task/{app_name}"),
		"message": workflow_notify_message(
			"Declarant notified to upload the UCR payment receipt on Create UCR (IDF).",
			result,
			audience=DECLARANT_AUDIENCE,
		),
	}


def notify_finance_verify_ucr_receipt_for_task(task) -> dict:
	if not is_ucr_payment_task_doc(task):
		return {"notified": 0}
	if not ucr_receipt_attached(task) and not task.get("custom_ucr_payment_receipt"):
		return {"notified": 0}

	result = send_notification(
		UCR_RECEIPT_VERIFY_FINANCE,
		task,
		audience=FINANCE_AUDIENCE,
	)
	return {
		**result,
		"message": workflow_notify_message(
			"Finance notified to verify the UCR payment receipt.",
			result,
			audience=FINANCE_AUDIENCE,
		),
	}


@frappe.whitelist()
def notify_finance_verify_ucr_receipt(task_name: str) -> dict:
	if not task_name or not frappe.db.exists("Task", task_name):
		return {"notified": 0}
	task = frappe.get_doc("Task", task_name)
	return notify_finance_verify_ucr_receipt_for_task(task)


def handle_ucr_application_receipt_upload(application_task) -> dict | None:
	if not is_ucr_create_task(application_task) or not application_task.project:
		return None

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
		copy_ucr_receipt_to_finance_task,
		get_ucr_receipt_line,
	)

	app_rec = get_ucr_receipt_line(application_task)
	if not app_rec or not app_rec.attachment:
		return None

	prev = application_task.get_doc_before_save()
	prev_rec = get_ucr_receipt_line(prev) if prev else None
	if prev_rec and prev_rec.attachment == app_rec.attachment:
		return None

	finance_name = copy_ucr_receipt_to_finance_task(application_task)
	if not finance_name:
		return None

	finance_task = frappe.get_doc("Task", finance_name)
	sync_ucr_finance_lines_to_idf_record(finance_task)
	return notify_finance_verify_ucr_receipt_for_task(finance_task)


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------


def validate_ucr_application_not_manually_completed(task) -> None:
	if frappe.flags.get("cgm_auto_completing_sea_task"):
		return
	if not is_ucr_create_task(task):
		return
	if task.status == "Completed" and can_complete_ucr_create_task(task):
		return
	frappe.throw(
		"Complete this task by attaching a verified <b>UCR Invoice</b>, the supplier "
		"<b>UCR Receipt</b>, and the <b>IDF/UCR certificate</b> on this form. "
		"The task will mark itself <b>Completed</b> automatically when all three are in place."
	)


def validate_finance_ucr_payment_task(task) -> None:
	if not is_ucr_payment_task_doc(task):
		return

	app_task = get_ucr_create_task(task.project) if task.project else None
	if app_task and not ucr_invoice_submitted(app_task):
		frappe.throw(
			"The declarant must submit the UCR invoice from <b>Create UCR (IDF)</b> first."
		)

	seed_ucr_finance_lines(task)

	if not (ucr_invoice_verified(task) or task.get("custom_ucr_invoice_verified")):
		frappe.throw(
			"Finance must tick <b>Verified by Finance</b> on the <b>UCR Invoice</b> row."
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

	if not (ucr_receipt_attached(task) or task.get("custom_ucr_payment_receipt")):
		frappe.throw(
			"The declarant must attach the <b>UCR Receipt</b> on <b>Create UCR (IDF)</b> before completion."
		)
	if not (ucr_receipt_verified(task) or task.get("custom_ucr_receipt_verified")):
		frappe.throw(
			"Finance must tick <b>Verified by Finance</b> on the <b>UCR Receipt</b> row."
		)


def enforce_ucr_finance_field_permissions(task) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
		enforce_finance_line_permissions,
	)

	enforce_finance_line_permissions(task)


# ------------------------------------------------------------------
# Completion
# ------------------------------------------------------------------


def mark_task_completed(task) -> None:
	frappe.db.set_value(
		"Task",
		task.name,
		{
			"status": "Completed",
			"completed_by": task.completed_by or frappe.session.user,
			"completed_on": task.completed_on or now_datetime(),
			"progress": 100,
		},
		update_modified=True,
	)
	frappe.clear_document_cache("Task", task.name)


def publish_task_completed_event(task) -> None:
	if not task.project:
		return
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{"task": task.name, "status": "Completed", "project": task.project},
	)
	frappe.publish_realtime(
		"cgm_project_tracking_refresh",
		{"project": task.project},
	)


def run_ucr_create_completion_hooks(task) -> None:
	sync_ucr_payment_to_idf_record(task)
	if task.project:
		run_project_refresh_hooks(task.project)
	publish_task_completed_event(task)


def run_ucr_payment_completion_hooks(task) -> None:
	sync_ucr_finance_lines_to_idf_record(task)
	close_ucr_application_when_finance_done(task)
	if task.project:
		run_project_refresh_hooks(task.project)
	publish_task_completed_event(task)


def auto_complete_task_if_ready(
	task,
	*,
	ready_check: Callable,
	completion_hooks: Callable,
) -> bool:
	if task.status in ("Completed", "Cancelled"):
		return False
	if not ready_check(task):
		return False

	frappe.flags.cgm_auto_completing_sea_task = True
	try:
		mark_task_completed(task)
		task.reload()
		completion_hooks(task)
	finally:
		frappe.flags.cgm_auto_completing_sea_task = False
	return True


def try_auto_complete_ucr_create_task(task) -> bool:
	return auto_complete_task_if_ready(
		task,
		ready_check=lambda t: can_complete_ucr_create_task(t),
		completion_hooks=run_ucr_create_completion_hooks,
	)


def try_auto_complete_ucr_payment_task(task) -> bool:
	return auto_complete_task_if_ready(
		task,
		ready_check=can_complete_ucr_payment_task,
		completion_hooks=run_ucr_payment_completion_hooks,
	)


def auto_complete_ucr_application_for_project(project: str) -> bool:
	if not project:
		return False
	app_name = get_ucr_create_task(project)
	if not app_name:
		return False
	app = frappe.get_doc("Task", app_name)
	if app.status in ("Completed", "Cancelled"):
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
		sync_ucr_status_from_finance_to_application,
	)

	sync_ucr_status_from_finance_to_application(app)
	app.reload()
	return try_auto_complete_ucr_create_task(app)


def close_ucr_application_when_finance_done(task) -> None:
	if not is_ucr_payment_task_doc(task) or task.status != "Completed" or not task.project:
		return
	auto_complete_ucr_application_for_project(task.project)


@frappe.whitelist()
def ensure_ucr_finance_lines(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
		ensure_ucr_finance_lines_saved,
		get_ucr_receipt_line,
	)

	added = ensure_ucr_finance_lines_saved(task)
	return {
		"added": added,
		"has_receipt_row": bool(get_ucr_receipt_line(task)),
		"task": task.name,
	}


@frappe.whitelist()
def get_ucr_declarant_workflow_status(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_create_task(task):
		frappe.throw("This status is only for <b>Create UCR (IDF)</b>.")

	finance_name = get_ucr_payment_task(task.project) if task.project else None
	finance_task = frappe.get_doc("Task", finance_name) if finance_name else None

	if task.status not in ("Completed", "Cancelled") and task.project:
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
			sync_ucr_status_from_finance_to_application,
		)

		if sync_ucr_status_from_finance_to_application(task):
			task.reload()
		if can_complete_ucr_create_task(task, finance_task):
			try_auto_complete_ucr_create_task(task)
			task.reload()

	inv = get_ucr_invoice_line(task)
	rec = get_ucr_receipt_line(task)
	fin_inv = get_ucr_invoice_line(finance_task) if finance_task else None
	fin_rec = get_ucr_receipt_line(finance_task) if finance_task else None

	payment_made = bool(
		finance_task
		and finance_task.get("custom_payment_entry")
		and int(
			frappe.db.get_value(
				"Payment Entry", finance_task.custom_payment_entry, "docstatus"
			)
			or 0
		)
		== 1
	)

	return {
		"finance_task": finance_name,
		"finance_task_url": get_url(f"/app/task/{finance_name}") if finance_name else None,
		"invoice_submitted": bool(task.get("custom_ucr_invoice_submitted")),
		"invoice_verified": bool(
			(inv and inv.verified)
			or task.get("custom_ucr_invoice_verified")
			or (fin_inv and fin_inv.verified)
		),
		"payment_made": payment_made,
		"receipt_attached": bool((rec and rec.attachment) or (fin_rec and fin_rec.attachment)),
		"receipt_verified": bool(
			(rec and rec.verified)
			or task.get("custom_ucr_receipt_verified")
			or (fin_rec and fin_rec.verified)
		),
		"finance_task_completed": bool(finance_task and finance_task.status == "Completed"),
		"idf_certificate_attached": idf_certificate_uploaded(task),
		"application_ready_to_complete": can_complete_ucr_create_task(task, finance_task),
		"task_status": task.status,
	}


@frappe.whitelist()
def ensure_ucr_finance_task_completed(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This action is only for <b>Finance pays UCR</b>.")
	completed = try_auto_complete_ucr_payment_task(task)
	task.reload()
	return {
		"task": task.name,
		"status": frappe.db.get_value("Task", task.name, "status"),
		"completed": completed,
	}


@frappe.whitelist()
def complete_ucr_finance_task(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This action is only for <b>Finance pays UCR</b>.")
	if not try_auto_complete_ucr_payment_task(task):
		frappe.throw("UCR payment workflow is not finished yet.")
	return {"task": task.name, "status": task.status}


@frappe.whitelist()
def ensure_ucr_invoice_synced(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This action is only for <b>Finance pays UCR</b>.")
	fin_inv = get_ucr_invoice_line(task)
	if fin_inv and fin_inv.attachment:
		return {"synced": False, "message": "UCR invoice already on this task."}
	if not task.project:
		return {"synced": False, "message": "Task has no project."}
	sync_ucr_invoice_to_finance_task(task.project)
	return {"synced": True, "message": "UCR invoice copied from declarant task."}


@frappe.whitelist()
def get_ucr_invoice_preview(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This preview is only for the UCR finance task.")
	if not task.project:
		return {"invoice_url": None, "finance_task": task_name, "finance_task_url": None}

	app_name = get_ucr_create_task(task.project)
	invoice_url = None
	fin_inv = get_ucr_invoice_line(task)
	if fin_inv and fin_inv.attachment:
		invoice_url = fin_inv.attachment
	elif app_name:
		app = frappe.get_doc("Task", app_name)
		inv = get_ucr_invoice_line(app)
		if inv and inv.attachment:
			invoice_url = inv.attachment
		if not invoice_url:
			invoice_url = legacy_ucr_invoice_url(app)

	needs_reload = bool(
		invoice_url and fin_inv and not fin_inv.attachment and app_name
	)

	return {
		"invoice_url": invoice_url,
		"needs_reload": needs_reload,
		"finance_task": task.name,
		"finance_task_url": get_url(f"/app/task/{task.name}"),
		"application_task": app_name,
		"application_task_url": get_url(f"/app/task/{app_name}") if app_name else None,
	}


def legacy_ucr_invoice_url(task) -> str | None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
		TASK_DOCUMENTS_FIELD,
		get_document_type_code,
	)

	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		code = get_document_type_code(row.document_type)
		if code in ("UCR_DOC", "UCR_INV", "UCR Invoice") and row.attachment:
			return row.attachment
	return None


@frappe.whitelist()
def verify_ucr_finance_line(task_name: str, line_type: str = "Invoice") -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	if not user_has_finance_department_access():
		frappe.throw("Only <b>Finance</b> can verify UCR invoice and receipt lines.")

	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This action is only for <b>Finance pays UCR</b>.")

	line_type = (line_type or "Invoice").strip()
	if line_type not in ("Invoice", "Receipt"):
		frappe.throw("Invalid line type.")

	seed_ucr_finance_lines(task)
	line = get_ucr_invoice_line(task) if line_type == "Invoice" else get_ucr_receipt_line(task)
	if not line:
		frappe.throw(f"<b>UCR {line_type}</b> row is missing on this task.")
	if not line.attachment:
		frappe.throw(f"Attach the <b>UCR {line_type}</b> before verifying.")

	line.verified = 1
	line.verified_by = frappe.session.user
	line.verified_on = now_datetime()
	if line_type == "Invoice" and task.meta.has_field("custom_ucr_invoice_verified"):
		task.custom_ucr_invoice_verified = 1
	elif line_type == "Receipt" and task.meta.has_field("custom_ucr_receipt_verified"):
		task.custom_ucr_receipt_verified = 1

	task.save()
	sync_ucr_finance_lines_to_idf_record(task)
	if line_type == "Invoice":
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
			sync_ucr_verification_to_application_task,
		)

		sync_ucr_verification_to_application_task(task)
		if task.project:
			auto_complete_ucr_application_for_project(task.project)
	elif line_type == "Receipt":
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
			sync_ucr_receipt_verification_to_application_task,
		)

		sync_ucr_receipt_verification_to_application_task(task)
	task.reload()
	completed = try_auto_complete_ucr_payment_task(task)
	label = line.line_label or f"UCR {line_type}"
	return {
		"task": task.name,
		"message": f"<b>{label}</b> verified.",
		"task_status": frappe.db.get_value("Task", task.name, "status"),
		"completed": completed,
	}


# ------------------------------------------------------------------
# Backward-compatible aliases
# ------------------------------------------------------------------

get_ucr_application_task = get_ucr_create_task
get_ucr_finance_task = get_ucr_payment_task
ucr_invoice_ready = ucr_invoice_submitted
ucr_finance_ready_to_complete = can_complete_ucr_payment_task
try_auto_complete_ucr_application_task = try_auto_complete_ucr_create_task
try_auto_complete_ucr_finance_task = try_auto_complete_ucr_payment_task
notify_operations_upload_ucr_receipt = notify_declarant_upload_ucr_receipt
idf_certificate_attached = idf_certificate_uploaded
