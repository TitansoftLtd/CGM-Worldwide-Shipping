"""Workflow orchestration for configuration-driven application + finance payment steps."""
from __future__ import annotations

from typing import Callable

import frappe
from frappe.utils import get_url, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
	APPLICATION_FINANCE_PROFILES,
	ApplicationFinanceProfile,
	all_profiles,
	can_complete_application_finance_task,
	can_complete_application_task,
	copy_application_receipt_to_finance_task,
	ensure_application_finance_lines_saved,
	get_application_finance_task,
	get_application_task,
	get_invoice_line,
	get_receipt_line,
	invoice_attached,
	invoice_submitted,
	is_application_finance_task,
	is_application_task,
	prepare_application_task_tables,
	profile_by_finance_kind,
	profile_for_task,
	project_has_submitted_invoice,
	receipt_attached,
	seed_application_finance_lines,
	sync_application_finance_lines_to_idf_record,
	sync_certificate_to_project,
	sync_invoice_verification_to_application_task,
	sync_receipt_verification_to_application_task,
	sync_status_from_finance_to_application,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
	send_notification,
	workflow_notify_message,
)

FINANCE_AUDIENCE = "Finance"
DECLARANT_AUDIENCE = "Declarant"
from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
	user_has_finance_department_access,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
	get_task_name_by_sequence,
	task_sequence,
)


def _profile_or_throw(task) -> ApplicationFinanceProfile:
	profile = profile_for_task(task)
	if not profile:
		frappe.throw("This action is not available for this task step.")
	return profile


def get_application_finance_task_by_profile(
	project: str, profile: ApplicationFinanceProfile
) -> str | None:
	return get_application_finance_task(project, profile)


def get_application_task_by_profile(
	project: str, profile: ApplicationFinanceProfile
) -> str | None:
	return get_application_task(project, profile)


def is_application_create_task(task, profile: ApplicationFinanceProfile) -> bool:
	return is_application_task(task_sequence(task), profile)


def is_application_payment_task_doc(task, profile: ApplicationFinanceProfile) -> bool:
	return is_application_finance_task(task_sequence(task), profile)


def application_finance_ready_to_complete(task, profile: ApplicationFinanceProfile) -> bool:
	return can_complete_application_finance_task(task, profile)


def sync_application_payment_hooks(task, profile: ApplicationFinanceProfile) -> None:
	sync_application_finance_lines_to_idf_record(task, profile)
	seq = task_sequence(task)
	if is_application_finance_task(seq, profile) and not frappe.flags.get(
		"cgm_syncing_application_receipt"
	):
		sync_invoice_verification_to_application_task(task, profile)
		sync_receipt_verification_to_application_task(task, profile)
	if is_application_task(seq, profile) or is_application_finance_task(seq, profile):
		sync_certificate_to_project(task, profile)


def sync_application_invoice_to_finance_task(
	project: str, profile: ApplicationFinanceProfile
) -> str | None:
	finance_name = get_application_finance_task(project, profile)
	if not finance_name:
		return None
	finance_task = frappe.get_doc("Task", finance_name)
	prepare_application_task_tables(finance_task, profile)
	finance_task.flags.ignore_links = True
	try:
		finance_task.save(ignore_permissions=True)
	finally:
		finance_task.flags.ignore_links = False
	return finance_name


def _invoice_pending_finance_notification(task, profile: ApplicationFinanceProfile) -> bool:
	if not is_application_create_task(task, profile):
		return False
	if (
		profile.application_submitted_field
		and task.get(profile.application_submitted_field)
	):
		return False
	return invoice_attached(task, profile)


def _notify_finance_for_application_invoice(
	task, profile: ApplicationFinanceProfile
) -> dict:
	if not task.project:
		frappe.throw("This task is not linked to a project.")
	finance_task_name = sync_application_invoice_to_finance_task(task.project, profile)
	if not finance_task_name:
		frappe.throw(
			f"Could not find the <b>{profile.finance_payment_kind}</b> finance task on this project. "
			"Regenerate the sea task plan."
		)
	finance_task = frappe.get_doc("Task", finance_task_name)
	notify_result = send_notification(
		profile.notification_invoice,
		finance_task,
		audience=FINANCE_AUDIENCE,
	)
	cert_label = profile.certificate_document_code.replace("_", "/")
	return {
		"task": task.name,
		"status": task.status,
		"finance_task": finance_task_name,
		"finance_task_url": get_url(f"/app/task/{finance_task_name}"),
		**notify_result,
		"message": workflow_notify_message(
			f"Finance notified. Declarant: upload the <b>{cert_label}</b> certificate "
			f"under <b>Clearance Documents</b> on the application task when it is issued.",
			notify_result,
			audience=FINANCE_AUDIENCE,
		),
	}


def auto_submit_application_invoice_to_finance_if_needed(
	task, profile: ApplicationFinanceProfile
) -> dict | None:
	flag_key = f"cgm_auto_submitting_{profile.key}_invoice"
	if frappe.flags.get(flag_key):
		return None
	if not _invoice_pending_finance_notification(task, profile):
		return None
	frappe.flags[flag_key] = True
	try:
		seed_application_finance_lines(task, profile)
		if profile.application_submitted_field and task.meta.has_field(
			profile.application_submitted_field
		):
			frappe.db.set_value(
				"Task",
				task.name,
				profile.application_submitted_field,
				1,
				update_modified=False,
			)
			setattr(task, profile.application_submitted_field, 1)
		sync_application_finance_lines_to_idf_record(task, profile)
		return _notify_finance_for_application_invoice(task, profile)
	finally:
		frappe.flags[flag_key] = False


def notify_declarant_upload_application_receipt(
	task, profile: ApplicationFinanceProfile
) -> dict:
	if not is_application_payment_task_doc(task, profile):
		return {"notified": 0}
	if not task.get("custom_payment_entry") and not task.get("custom_journal_entry"):
		return {"notified": 0}
	if not task.project:
		return {"notified": 0}
	app_name = get_application_task(task.project, profile)
	if not app_name:
		return {"notified": 0}
	app = frappe.get_doc("Task", app_name)
	seed_application_finance_lines(app, profile)
	try:
		app.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title=f"{profile.receipt_label} seeding failed",
			message=f"Could not seed finance lines on {app_name}: {frappe.get_traceback()}",
		)
	result = send_notification(
		profile.notification_receipt_declarant,
		app,
		audience=DECLARANT_AUDIENCE,
	)
	return {
		**result,
		"application_task": app_name,
		"application_task_url": get_url(f"/app/task/{app_name}"),
		"message": workflow_notify_message(
			f"Declarant notified to upload the <b>{profile.receipt_label}</b> on the application task.",
			result,
			audience=DECLARANT_AUDIENCE,
		),
	}


def notify_finance_verify_application_receipt(
	task, profile: ApplicationFinanceProfile
) -> dict:
	if not is_application_payment_task_doc(task, profile):
		return {"notified": 0}
	if not receipt_attached(task, profile):
		return {"notified": 0}
	result = send_notification(
		profile.notification_receipt_verify,
		task,
		audience=FINANCE_AUDIENCE,
	)
	return {
		**result,
		"message": workflow_notify_message(
			f"Finance notified to verify the <b>{profile.receipt_label}</b>.",
			result,
			audience=FINANCE_AUDIENCE,
		),
	}


def handle_application_receipt_upload(
	application_task, profile: ApplicationFinanceProfile
) -> dict | None:
	if not is_application_create_task(application_task, profile) or not application_task.project:
		return None
	app_rec = get_receipt_line(application_task, profile)
	if not app_rec or not app_rec.attachment:
		return None
	prev = application_task.get_doc_before_save()
	prev_rec = get_receipt_line(prev, profile) if prev else None
	if prev_rec and prev_rec.attachment == app_rec.attachment:
		return None
	finance_name = copy_application_receipt_to_finance_task(application_task, profile)
	if not finance_name:
		return None
	finance_task = frappe.get_doc("Task", finance_name)
	sync_application_finance_lines_to_idf_record(finance_task, profile)
	return notify_finance_verify_application_receipt(finance_task, profile)


def validate_application_not_manually_completed(
	task, profile: ApplicationFinanceProfile
) -> None:
	if frappe.flags.get("cgm_auto_completing_sea_task"):
		return
	if not is_application_create_task(task, profile):
		return
	if task.status == "Completed" and can_complete_application_task(task, profile):
		return
	cert_hint = (
		f", the <b>{profile.receipt_label}</b>, and the <b>{profile.certificate_document_code}</b> "
		f"certificate"
		if profile.certificate_document_code
		else f" and the <b>{profile.receipt_label}</b>"
	)
	frappe.throw(
		f"Complete this task by attaching a verified <b>{profile.invoice_label}</b>{cert_hint} "
		f"on this form. The task will mark itself <b>Completed</b> automatically "
		"when all requirements are in place."
	)


def validate_finance_application_payment_task(
	task, profile: ApplicationFinanceProfile
) -> None:
	if not is_application_payment_task_doc(task, profile):
		return
	app_task = get_application_task(task.project, profile) if task.project else None
	if app_task and not invoice_submitted(app_task, profile):
		frappe.throw("The declarant must submit the application invoice first.")
	seed_application_finance_lines(task, profile)
	inv_ok = get_invoice_line(task, profile) and get_invoice_line(task, profile).verified
	if profile.application_invoice_verified_field:
		inv_ok = inv_ok or bool(task.get(profile.application_invoice_verified_field))
	if not inv_ok:
		frappe.throw(
			f"Finance must tick <b>Verified by Finance</b> on the <b>{profile.invoice_label}</b> row."
		)
	task_fields = frappe.get_meta("Task")
	if task_fields.has_field("custom_purchase_invoice") and not task.get("custom_purchase_invoice"):
		frappe.throw("Create and submit a <b>Purchase Invoice</b> from this task before completion.")
	has_payment = task.get("custom_payment_entry") or task.get("custom_journal_entry")
	if not has_payment:
		frappe.throw(
			"Record payment via <b>Make Payment</b> (Journal Entry) or <b>Payment Entry</b> "
			"before completion."
		)
	if task.get("custom_payment_entry"):
		pe_status = frappe.db.get_value("Payment Entry", task.custom_payment_entry, "docstatus")
		if int(pe_status or 0) != 1:
			frappe.throw("Payment Entry must be <b>submitted</b> before completing this task.")
	if not receipt_attached_for_payment_workflow(task, profile):
		frappe.throw(
			f"The declarant must attach the <b>{profile.receipt_label}</b> on the application task "
			"before completion."
		)
	rec_ok = get_receipt_line(task, profile) and get_receipt_line(task, profile).verified
	if profile.application_receipt_verified_field:
		rec_ok = rec_ok or bool(task.get(profile.application_receipt_verified_field))
	if not rec_ok:
		frappe.throw(
			f"Finance must tick <b>Verified by Finance</b> on the <b>{profile.receipt_label}</b> row."
		)


def receipt_attached_for_payment_workflow(
	task, profile: ApplicationFinanceProfile
) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		receipt_attached_for_payment_workflow as _attached,
	)

	return _attached(task, profile)


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


def run_application_create_completion_hooks(
	task, profile: ApplicationFinanceProfile
) -> None:
	sync_application_payment_hooks(task, profile)
	if task.project:
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			run_project_refresh_hooks,
		)

		run_project_refresh_hooks(task.project)
	publish_task_completed_event(task)


def run_application_payment_completion_hooks(
	task, profile: ApplicationFinanceProfile
) -> None:
	sync_application_finance_lines_to_idf_record(task, profile)
	close_application_when_finance_done(task, profile)
	if task.project:
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			run_project_refresh_hooks,
		)

		run_project_refresh_hooks(task.project)
	publish_task_completed_event(task)


def auto_complete_task_if_ready(
	task,
	*,
	profile: ApplicationFinanceProfile,
	ready_check: Callable,
	completion_hooks: Callable,
) -> bool:
	if task.status in ("Completed", "Cancelled"):
		return False
	if not ready_check(task, profile):
		return False
	frappe.flags.cgm_auto_completing_sea_task = True
	try:
		mark_task_completed(task)
		task.reload()
		completion_hooks(task, profile)
	finally:
		frappe.flags.cgm_auto_completing_sea_task = False
	return True


def try_auto_complete_application_task(
	task, profile: ApplicationFinanceProfile
) -> bool:
	return auto_complete_task_if_ready(
		task,
		profile=profile,
		ready_check=can_complete_application_task,
		completion_hooks=run_application_create_completion_hooks,
	)


def try_auto_complete_application_finance_task(
	task, profile: ApplicationFinanceProfile
) -> bool:
	return auto_complete_task_if_ready(
		task,
		profile=profile,
		ready_check=can_complete_application_finance_task,
		completion_hooks=run_application_payment_completion_hooks,
	)


def auto_complete_application_for_project(
	project: str, profile: ApplicationFinanceProfile
) -> bool:
	if not project:
		return False
	app_name = get_application_task(project, profile)
	if not app_name:
		return False
	app = frappe.get_doc("Task", app_name)
	if app.status in ("Completed", "Cancelled"):
		return False
	if sync_status_from_finance_to_application(app, profile):
		app.reload()
	return try_auto_complete_application_task(app, profile)


def close_application_when_finance_done(
	task, profile: ApplicationFinanceProfile
) -> None:
	if not is_application_payment_task_doc(task, profile):
		return
	if task.status != "Completed" or not task.project:
		return
	auto_complete_application_for_project(task.project, profile)


@frappe.whitelist()
def ensure_application_finance_lines(task_name: str, profile_key: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	profile = _profile_by_key(profile_key)
	task = frappe.get_doc("Task", task_name)
	added = ensure_application_finance_lines_saved(task, profile)
	return {
		"added": added,
		"has_receipt_row": bool(get_receipt_line(task, profile)),
		"task": task.name,
	}


@frappe.whitelist()
def get_application_declarant_workflow_status(
	task_name: str, profile_key: str
) -> dict:
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	profile = _profile_by_key(profile_key)
	task = frappe.get_doc("Task", task_name)
	if not is_application_create_task(task, profile):
		frappe.throw("This status is only for the application task.")

	finance_name = get_application_finance_task(task.project, profile) if task.project else None
	finance_task = frappe.get_doc("Task", finance_name) if finance_name else None

	if task.status not in ("Completed", "Cancelled") and task.project:
		if sync_status_from_finance_to_application(task, profile):
			task.reload()
		if can_complete_application_task(task, profile, finance_task):
			try_auto_complete_application_task(task, profile)
			task.reload()

	inv = get_invoice_line(task, profile)
	rec = get_receipt_line(task, profile)
	fin_inv = get_invoice_line(finance_task, profile) if finance_task else None
	fin_rec = get_receipt_line(finance_task, profile) if finance_task else None

	payment_made = bool(
		finance_task
		and (
			(
				finance_task.get("custom_payment_entry")
				and int(
					frappe.db.get_value(
						"Payment Entry", finance_task.custom_payment_entry, "docstatus"
					)
					or 0
				)
				== 1
			)
			or finance_task.get("custom_journal_entry")
		)
	)

	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		certificate_uploaded,
	)

	return {
		"finance_task": finance_name,
		"finance_task_url": get_url(f"/app/task/{finance_name}") if finance_name else None,
		"invoice_submitted": bool(
			profile.application_submitted_field and task.get(profile.application_submitted_field)
		)
		or invoice_attached(task, profile),
		"invoice_verified": bool(
			(inv and inv.verified)
			or (
				profile.application_invoice_verified_field
				and task.get(profile.application_invoice_verified_field)
			)
			or (fin_inv and fin_inv.verified)
		),
		"payment_made": payment_made,
		"receipt_attached": bool((rec and rec.attachment) or (fin_rec and fin_rec.attachment)),
		"receipt_verified": bool(
			(rec and rec.verified)
			or (
				profile.application_receipt_verified_field
				and task.get(profile.application_receipt_verified_field)
			)
			or (fin_rec and fin_rec.verified)
		),
		"finance_task_completed": bool(finance_task and finance_task.status == "Completed"),
		"certificate_attached": certificate_uploaded(task, profile),
		"application_ready_to_complete": can_complete_application_task(
			task, profile, finance_task
		),
		"task_status": task.status,
		"profile_key": profile.key,
		"invoice_label": profile.invoice_label,
		"receipt_label": profile.receipt_label,
	}


@frappe.whitelist()
def ensure_application_finance_task_completed(
	task_name: str, profile_key: str
) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	profile = _profile_by_key(profile_key)
	task = frappe.get_doc("Task", task_name)
	if not is_application_payment_task_doc(task, profile):
		frappe.throw(f"This action is only for the <b>{profile.finance_payment_kind}</b> finance task.")
	completed = try_auto_complete_application_finance_task(task, profile)
	task.reload()
	return {
		"task": task.name,
		"status": frappe.db.get_value("Task", task.name, "status"),
		"completed": completed,
	}


@frappe.whitelist()
def verify_application_finance_line(
	task_name: str, profile_key: str, line_type: str = "Invoice"
) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	if not user_has_finance_department_access():
		frappe.throw("Only <b>Finance</b> can verify invoice and receipt lines.")
	profile = _profile_by_key(profile_key)
	task = frappe.get_doc("Task", task_name)
	if not is_application_payment_task_doc(task, profile):
		frappe.throw(f"This action is only for the <b>{profile.finance_payment_kind}</b> finance task.")
	line_type = (line_type or "Invoice").strip()
	if line_type not in ("Invoice", "Receipt"):
		frappe.throw("Invalid line type.")
	seed_application_finance_lines(task, profile)
	line = (
		get_invoice_line(task, profile)
		if line_type == "Invoice"
		else get_receipt_line(task, profile)
	)
	if not line:
		frappe.throw(f"<b>{profile.invoice_label if line_type == 'Invoice' else profile.receipt_label}</b> row is missing.")
	if not line.attachment:
		frappe.throw(
			f"Attach the <b>{profile.invoice_label if line_type == 'Invoice' else profile.receipt_label}</b> before verifying."
		)
	line.verified = 1
	line.verified_by = frappe.session.user
	line.verified_on = now_datetime()
	if line_type == "Invoice" and profile.application_invoice_verified_field:
		if task.meta.has_field(profile.application_invoice_verified_field):
			setattr(task, profile.application_invoice_verified_field, 1)
	elif line_type == "Receipt" and profile.application_receipt_verified_field:
		if task.meta.has_field(profile.application_receipt_verified_field):
			setattr(task, profile.application_receipt_verified_field, 1)
	task.save()
	sync_application_finance_lines_to_idf_record(task, profile)
	if line_type == "Invoice":
		sync_invoice_verification_to_application_task(task, profile)
		if task.project:
			auto_complete_application_for_project(task.project, profile)
	elif line_type == "Receipt":
		sync_receipt_verification_to_application_task(task, profile)
	task.reload()
	completed = try_auto_complete_application_finance_task(task, profile)
	label = line.line_label or profile.invoice_label
	return {
		"task": task.name,
		"message": f"<b>{label}</b> verified.",
		"task_status": frappe.db.get_value("Task", task.name, "status"),
		"completed": completed,
	}


def _profile_by_key(profile_key: str) -> ApplicationFinanceProfile:
	for profile in all_profiles():
		if profile.key == profile_key:
			return profile
	frappe.throw(f"Unknown application finance profile: <b>{profile_key}</b>")


def process_application_workflow_on_update(task) -> None:
	"""Run auto-submit, receipt sync, and auto-complete for all configured profiles."""
	profile = profile_for_task(task)
	if not profile:
		return
	seq = task_sequence(task)
	if is_application_task(seq, profile) and task.status not in ("Completed", "Cancelled"):
		auto_submit_application_invoice_to_finance_if_needed(task, profile)
		handle_application_receipt_upload(task, profile)
		try_auto_complete_application_task(task, profile)
	elif is_application_finance_task(seq, profile) and task.status not in (
		"Completed",
		"Cancelled",
	):
		try_auto_complete_application_finance_task(task, profile)


def process_application_workflow_onload(task) -> bool:
	"""Seed lines, sync status, auto-complete on form open. Returns True if task was updated."""
	profile = profile_for_task(task)
	if not profile:
		return False
	changed = ensure_application_finance_lines_saved(task, profile)
	seq = task_sequence(task)
	if is_application_task(seq, profile):
		changed = sync_status_from_finance_to_application(task, profile) or changed
		if task.status not in ("Completed", "Cancelled"):
			if try_auto_complete_application_task(task, profile):
				changed = True
	elif is_application_finance_task(seq, profile) and task.status not in (
		"Completed",
		"Cancelled",
	):
		if task.project:
			app_name = get_application_task(task.project, profile)
			if app_name:
				copy_application_receipt_to_finance_task(frappe.get_doc("Task", app_name), profile)
				task.reload()
			if try_auto_complete_application_finance_task(task, profile):
				changed = True
	return changed


def enforce_entry_finance_gate(project: str) -> None:
	profile = APPLICATION_FINANCE_PROFILES["Entry Application"]
	finance_task_name = get_application_finance_task(project, profile)
	if not finance_task_name:
		frappe.throw(
			"Generate the sea task plan and complete <b>Finance Pays Entry Slip</b> first."
		)
	finance_task = frappe.get_doc("Task", finance_task_name)
	if finance_task.status != "Completed" or not can_complete_application_finance_task(
		finance_task, profile
	):
		frappe.throw(
			"Cannot move to <b>Entry Paid</b> until <b>Finance Pays Entry Slip</b> is completed: "
			"Entry Slip invoice verified, payment recorded, receipt verified, and ENTRY document uploaded."
		)
