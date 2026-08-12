"""Workflow orchestration for configuration-driven application + finance payment steps."""
from __future__ import annotations

from typing import Callable

import frappe
from frappe.utils import cint, flt, get_url, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
	APPLICATION_FINANCE_PROFILES,
	ApplicationFinanceProfile,
	all_profiles,
	can_complete_application_finance_task,
	can_complete_application_task,
	certificate_uploaded,
	copy_application_receipt_to_finance_task,
	ensure_application_finance_lines_saved,
	ensure_application_receipt_on_finance_task,
	get_application_finance_task,
	get_application_task,
	get_invoice_line,
	get_pop_line,
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
	receipt_attached_for_payment_workflow,
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		task_matches_application_finance,
	)

	return task_matches_application_finance(task, profile)


def application_finance_ready_to_complete(task, profile: ApplicationFinanceProfile) -> bool:
	return can_complete_application_finance_task(task, profile)


def sync_application_payment_hooks(task, profile: ApplicationFinanceProfile) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		sync_invoice_line_client_paid_to_task_field,
	)

	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		task_matches_application,
		task_matches_application_finance,
	)

	sync_invoice_line_client_paid_to_task_field(task, profile)
	sync_application_finance_lines_to_idf_record(task, profile)
	if task_matches_application_finance(task, profile) and not frappe.flags.get(
		"cgm_syncing_application_receipt"
	):
		sync_invoice_verification_to_application_task(task, profile)
		sync_receipt_verification_to_application_task(task, profile)
	if task_matches_application(task, profile) or task_matches_application_finance(
		task, profile
	):
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
	task, profile: ApplicationFinanceProfile, *, strict: bool = True
) -> dict | None:
	if not task.project:
		frappe.throw("This task is not linked to a project.")
	finance_task_name = sync_application_invoice_to_finance_task(task.project, profile)
	if not finance_task_name:
		msg = (
			f"Could not find the <b>{profile.finance_payment_kind}</b> finance task on this project. "
			"Regenerate the sea task plan."
		)
		if strict:
			frappe.throw(msg)
		frappe.msgprint(msg, indicator="orange", alert=True)
		return None
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
		result = _notify_finance_for_application_invoice(task, profile, strict=False)
		if not result:
			return None
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
		return result
	finally:
		frappe.flags[flag_key] = False


def notify_finance_upload_application_receipt(
	task, profile: ApplicationFinanceProfile
) -> dict:
	"""After payment: prompt Finance to attach the receipt on this finance task."""
	if not is_application_payment_task_doc(task, profile):
		return {"notified": 0}
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		task_has_recorded_payment,
	)

	if not task_has_recorded_payment(task):
		return {"notified": 0}
	seed_application_finance_lines(task, profile)
	try:
		task.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title=f"{profile.receipt_label} seeding failed",
			message=f"Could not seed finance lines on {task.name}: {frappe.get_traceback()}",
		)
	result = send_notification(
		profile.notification_receipt_declarant,
		task,
		audience=FINANCE_AUDIENCE,
	)
	label = profile.pop_label if profile.requires_pop else profile.receipt_label
	return {
		**result,
		"task": task.name,
		"task_url": get_url(f"/app/task/{task.name}"),
		"message": workflow_notify_message(
			f"Finance notified to attach <b>{label}</b> when available.",
			result,
			audience=FINANCE_AUDIENCE,
		),
	}


# Backward-compatible alias — receipt upload is now Finance-owned.
notify_declarant_upload_application_receipt = notify_finance_upload_application_receipt


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
	"""Legacy path: if an open project still has a receipt on the application task, sync it."""
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


def handle_finance_receipt_upload(
	finance_task, profile: ApplicationFinanceProfile
) -> dict | None:
	"""When a receipt is attached on finance: mirror to application; auto-confirm unless POP flow."""
	if not is_application_payment_task_doc(finance_task, profile) or not finance_task.project:
		return None
	fin_rec = get_receipt_line(finance_task, profile)
	if not fin_rec or not fin_rec.attachment:
		return None
	prev = finance_task.get_doc_before_save()
	prev_rec = get_receipt_line(prev, profile) if prev else None
	if prev_rec and prev_rec.attachment == fin_rec.attachment and cint(prev_rec.verified):
		# Still ensure Declarant can see it (e.g. open project mid-flight).
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			copy_finance_receipt_to_application_task,
		)

		copy_finance_receipt_to_application_task(finance_task, profile)
		return None
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		copy_finance_receipt_to_application_task,
	)

	# Shipping Line: Documentation attaches; Finance must verify manually — do not auto-stamp.
	if not profile.requires_pop:
		# Persist auto-verified stamp if normalize ran in-memory only.
		if fin_rec.name and not cint(
			frappe.db.get_value("Task Finance Line", fin_rec.name, "verified")
		):
			frappe.db.set_value(
				"Task Finance Line",
				fin_rec.name,
				{
					"verified": 1,
					"verified_by": frappe.session.user,
					"verified_on": now_datetime(),
				},
				update_modified=False,
			)
			if profile.application_receipt_verified_field and finance_task.meta.has_field(
				profile.application_receipt_verified_field
			):
				frappe.db.set_value(
					"Task",
					finance_task.name,
					profile.application_receipt_verified_field,
					1,
					update_modified=False,
				)
			finance_task.reload()

	copy_finance_receipt_to_application_task(finance_task, profile)
	sync_application_finance_lines_to_idf_record(finance_task, profile)
	return None


def validate_application_not_manually_completed(
	task, profile: ApplicationFinanceProfile
) -> None:
	if frappe.flags.get("cgm_auto_completing_sea_task"):
		return
	if not is_application_create_task(task, profile):
		return
	if task.status == "Completed" and can_complete_application_task(task, profile):
		return
	if profile.requires_pop:
		frappe.throw(
			f"This task completes automatically after Finance verifies the "
			f"<b>{profile.receipt_label}</b> (once POP is shared and Documentation attaches the receipt)."
		)
	if profile.complete_on_invoice_verified:
		frappe.throw(
			f"This task completes automatically after Finance verifies the "
			f"<b>{profile.invoice_label}</b>."
		)
	finance_name = get_application_finance_task(task.project, profile) if task.project else None
	finance_task = frappe.get_doc("Task", finance_name) if finance_name else None
	if finance_task:
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			task_client_paid_directly,
		)

		if task_client_paid_directly(finance_task):
			if (
				profile.certificate_document_code or profile.legacy_certificate_codes
			) and not certificate_uploaded(task, profile):
				frappe.throw(
					f"Attach the required <b>{profile.certificate_document_code}</b> "
					"certificate before completing this task."
				)
			# Client-pays with no certificate: allow explicit Mark Completed after
			# invoice handoff; Finance still owns verify + client receipt.
			return
	cert_hint = (
		f" and the <b>{profile.certificate_document_code}</b> certificate"
		if profile.certificate_document_code
		else ""
	)
	frappe.throw(
		f"Complete this task by attaching a verified <b>{profile.invoice_label}</b>{cert_hint} "
		f"on this form. Finance uploads the <b>{profile.receipt_label}</b> after payment. "
		"The task will mark itself <b>Completed</b> automatically when all requirements are in place."
	)


def validate_finance_application_payment_task(
	task, profile: ApplicationFinanceProfile
) -> None:
	if not is_application_payment_task_doc(task, profile):
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		client_paid_settlement_ready,
		task_client_paid_directly,
		task_has_recorded_payment,
	)

	# Client-pays: verify invoice; skip JE / Purchase Invoice.
	# Receipt remains required when profile.requires_receipt_verification (not Entry).
	if task_client_paid_directly(task):
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
		if profile.requires_pop:
			from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
				pop_attached,
				receipt_verified,
			)

			if not pop_attached(task, profile):
				frappe.throw(
					f"Attach the client's <b>{profile.pop_label or 'POP'}</b> "
					"(portal upload or Finance) before completion."
				)
			if not receipt_attached_for_payment_workflow(task, profile):
				frappe.throw(
					f"Documentation must attach the <b>{profile.receipt_label}</b> using the POP."
				)
			if not receipt_verified(task, profile):
				frappe.throw(
					f"Finance must verify the <b>{profile.receipt_label}</b> before completion."
				)
			return
		if not client_paid_settlement_ready(task):
			frappe.throw(
				"Client-pays path is not complete: verify the invoice first."
			)
		if profile.requires_receipt_verification:
			from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
				receipt_verified,
			)

			if not receipt_attached_for_payment_workflow(task, profile):
				frappe.throw(
					f"Attach the <b>{profile.receipt_label}</b> before completing this task."
				)
			if not receipt_verified(task, profile):
				frappe.throw(
					f"Finance must verify the <b>{profile.receipt_label}</b> before completion."
				)
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
	if not task_has_recorded_payment(task):
		frappe.throw(
			"Record payment via <b>Make Payment</b> (Journal Entry) or <b>Payment Entry</b> "
			"before completion, or tick <b>Client will pay</b> if the client settles it."
		)
	if task.get("custom_payment_entry"):
		pe_status = frappe.db.get_value("Payment Entry", task.custom_payment_entry, "docstatus")
		if int(pe_status or 0) != 1:
			frappe.throw("Payment Entry must be <b>submitted</b> before completing this task.")
	if profile.requires_receipt_verification:
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			receipt_verified,
		)

		if not receipt_attached_for_payment_workflow(task, profile):
			frappe.throw(
				f"Attach the <b>{profile.receipt_label}</b> after payment before completing this task."
			)
		if not receipt_verified(task, profile):
			frappe.throw(
				f"Finance must verify the <b>{profile.receipt_label}</b> before completion."
			)
	if profile.requires_pop:
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			pop_attached,
			receipt_verified,
		)

		if not pop_attached(task, profile):
			frappe.throw(
				f"Attach the bank <b>{profile.pop_label or 'POP'}</b> after recording payment."
			)
		if not receipt_attached_for_payment_workflow(task, profile):
			frappe.throw(
				f"Documentation must attach the <b>{profile.receipt_label}</b> using the POP."
			)
		if not receipt_verified(task, profile):
			frappe.throw(
				f"Finance must verify the <b>{profile.receipt_label}</b> before completion."
			)


def receipt_attached_for_payment_workflow(
	task, profile: ApplicationFinanceProfile
) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		receipt_attached_for_payment_workflow as _attached,
	)

	return _attached(task, profile)


def mark_task_completed(task) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		mark_task_completed as _mark,
	)

	_mark(task)


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
		if profile.payment_item == "Shipping Line":
			from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
				sync_project_deposit_payment_statuses,
			)

			sync_project_deposit_payment_statuses(task.project)
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
def sync_application_receipt_for_finance_task(
	task_name: str, profile_key: str
) -> dict:
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	profile = _profile_by_key(profile_key)
	task = frappe.get_doc("Task", task_name)
	if not is_application_payment_task_doc(task, profile):
		frappe.throw(f"This action is only for the <b>{profile.finance_payment_kind}</b> finance task.")
	had_receipt = receipt_attached(task, profile)
	synced = ensure_application_receipt_on_finance_task(task, profile) and not had_receipt
	task.reload()
	return {
		"synced": synced,
		"receipt_attached": receipt_attached_for_payment_workflow(task, profile),
	}


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

	# Read-only status for the form intro. Do not sync/complete here — onload and
	# save hooks own mutations. Side effects here caused Open↔Completed flicker.

	inv = get_invoice_line(task, profile)
	rec = get_receipt_line(task, profile)
	fin_inv = get_invoice_line(finance_task, profile) if finance_task else None
	fin_rec = get_receipt_line(finance_task, profile) if finance_task else None

	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		certificate_uploaded,
		finance_has_client_paid_invoice_line,
		pop_attached,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		task_client_paid_directly,
		task_has_recorded_payment,
	)

	client_paid = bool(
		finance_task
		and (
			task_client_paid_directly(finance_task)
			or finance_has_client_paid_invoice_line(finance_task, profile)
		)
	)
	payment_made = bool(finance_task and task_has_recorded_payment(finance_task))

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
		"pop_attached": bool(
			profile.requires_pop
			and (
				pop_attached(task, profile)
				or (finance_task and pop_attached(finance_task, profile))
			)
		),
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
		"client_paid_directly": client_paid,
		"certificate_required": bool(
			(profile.certificate_document_code or profile.legacy_certificate_codes)
			and not profile.complete_on_invoice_verified
		),
		"certificate_attached": certificate_uploaded(task, profile),
		"application_ready_to_complete": can_complete_application_task(
			task, profile, finance_task
		),
		"task_status": task.status,
		"profile_key": profile.key,
		"invoice_label": profile.invoice_label,
		"receipt_label": profile.receipt_label,
		"pop_label": profile.pop_label if profile.requires_pop else "",
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
	task_name: str,
	profile_key: str,
	line_type: str = "Invoice",
	finance_line_name: str | None = None,
) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	profile = _profile_by_key(profile_key)
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		ACTION_VERIFY_INVOICE,
		flow_for_profile,
		throw_unless_responsibility,
	)

	throw_unless_responsibility(
		flow_for_profile(profile),
		ACTION_VERIFY_INVOICE,
		label="verify invoice and receipt lines",
	)
	task = frappe.get_doc("Task", task_name)
	if not is_application_payment_task_doc(task, profile):
		frappe.throw(f"This action is only for the <b>{profile.finance_payment_kind}</b> finance task.")
	line_type = (line_type or "Invoice").strip()
	if line_type not in ("Invoice", "Receipt", "POP"):
		frappe.throw("Invalid line type.")
	seed_application_finance_lines(task, profile)
	if line_type == "Receipt":
		ensure_application_receipt_on_finance_task(task, profile)
		task.reload()
		seed_application_finance_lines(task, profile)
	if line_type == "Invoice":
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			get_invoice_lines,
		)

		line = None
		if finance_line_name:
			for row in get_invoice_lines(task, profile):
				if row.name == finance_line_name:
					line = row
					break
			if not line:
				frappe.throw("Invoice line not found on this task.")
		else:
			# Prefer first unverified attached invoice (covers amendments).
			for row in get_invoice_lines(task, profile):
				if row.get("attachment") and not cint(row.get("verified")):
					line = row
					break
			if not line:
				line = get_invoice_line(task, profile)
		label_fallback = profile.invoice_label
	elif line_type == "POP":
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			get_pop_line,
		)

		line = get_pop_line(task, profile)
		label_fallback = profile.pop_label or "POP"
	else:
		line = get_receipt_line(task, profile)
		label_fallback = profile.receipt_label
	if not line:
		frappe.throw(f"<b>{label_fallback}</b> row is missing.")
	if not line.attachment:
		if line_type == "Receipt" and receipt_attached_for_payment_workflow(task, profile):
			app_name = get_application_task(task.project, profile) if task.project else None
			app_line = (
				get_receipt_line(frappe.get_doc("Task", app_name), profile) if app_name else None
			)
			if app_line and app_line.attachment:
				line.attachment = app_line.attachment
		if not line.attachment:
			if line_type == "Receipt":
				frappe.throw(
					f"The <b>{profile.receipt_label}</b> must be attached "
					f"{'by Documentation using the POP' if profile.requires_pop else 'on the linked application task'} "
					"before Finance can verify it."
				)
			frappe.throw(f"Attach the <b>{label_fallback}</b> before verifying.")
	if line_type == "POP":
		frappe.throw(
			f"<b>{profile.pop_label or 'POP'}</b> does not need Finance verification — "
			"Documentation uses it to attach the shipping line receipt."
		)
	line.verified = 1
	line.verified_by = frappe.session.user
	line.verified_on = now_datetime()
	if line_type == "Invoice" and profile.application_invoice_verified_field:
		# Task-level flag means all attached invoices verified (legacy readers).
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			all_invoice_lines_verified,
		)

		if task.meta.has_field(profile.application_invoice_verified_field) and all_invoice_lines_verified(
			task, profile
		):
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
	label = line.line_label or label_fallback
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


def application_finance_needs_work(finance_task, profile: ApplicationFinanceProfile) -> bool:
	"""True when Finance still needs verify/pay on any invoice line (and Shipping Line POP/receipt)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		all_invoice_lines_settled,
		all_invoice_lines_verified,
		get_invoice_lines,
		pop_attached,
		receipt_verified,
		unpaid_invoice_lines,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		task_client_paid_directly,
		task_has_recorded_payment,
	)

	rows = [r for r in get_invoice_lines(finance_task, profile) if r.get("attachment")]
	if not rows:
		return False
	if not all_invoice_lines_verified(finance_task, profile):
		return True
	if unpaid_invoice_lines(finance_task, profile):
		return True
	# Legacy single-invoice path.
	if len(rows) == 1 and not cint(rows[0].get("is_amendment")):
		if not task_client_paid_directly(finance_task) and not task_has_recorded_payment(
			finance_task
		):
			return True
	elif not all_invoice_lines_settled(finance_task, profile):
		return True
	if profile.requires_pop:
		if not pop_attached(finance_task, profile):
			return True
		if not receipt_attached_for_payment_workflow(finance_task, profile):
			return True
		if not receipt_verified(finance_task, profile):
			return True
	if profile.requires_receipt_verification:
		if not receipt_attached_for_payment_workflow(finance_task, profile):
			return True
		if not receipt_verified(finance_task, profile):
			return True
	return False


def application_invoice_fingerprint(task, profile: ApplicationFinanceProfile) -> tuple:
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		get_invoice_lines,
	)

	inv_rows = get_invoice_lines(task, profile)
	rec = get_receipt_line(task, profile)
	pop = get_pop_line(task, profile) if profile.requires_pop else None
	invoice_fp = tuple(
		(
			(r.get("attachment") or ""),
			cint(r.get("verified")),
			cint(r.get("is_amendment")),
			(r.get("journal_entry") or ""),
			cint(r.get("client_paid_directly")),
			cint(r.get("client_reported_paid")),
			(r.get("line_label") or ""),
		)
		for r in inv_rows
	)
	return (
		invoice_fp,
		(pop.get("attachment") if pop else "") or "",
		(rec.get("attachment") if rec else "") or "",
		cint(rec.get("verified") if rec else 0),
		(task.get("custom_journal_entry") or ""),
		(task.get("custom_payment_entry") or ""),
		cint(task.get("custom_client_paid_directly")),
	)


def application_invoice_work_changed(task, profile: ApplicationFinanceProfile) -> bool:
	prev = task.get_doc_before_save()
	if not prev:
		return True
	return application_invoice_fingerprint(task, profile) != application_invoice_fingerprint(
		prev, profile
	)


def reopen_application_finance_if_pending_work(
	finance_task, profile: ApplicationFinanceProfile
) -> dict | None:
	"""Reopen Completed finance (and app) when invoice still needs verify/pay/receipt."""
	if frappe.flags.get("cgm_reopening_task") or frappe.flags.get("cgm_auto_completing_sea_task"):
		return None
	if not is_application_payment_task_doc(finance_task, profile):
		return None
	if finance_task.status == "Cancelled":
		return None
	if not application_finance_needs_work(finance_task, profile):
		return None
	if finance_task.status != "Completed":
		return {
			"reopened": [],
			"finance_task": finance_task.name,
		}

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import _reopen_sea_task

	reopened: list[str] = []
	frappe.flags.cgm_reopening_task = True
	try:
		if _reopen_sea_task(
			finance_task,
			reason=f"Additional {profile.invoice_label} needs verification and payment",
		):
			reopened.append(finance_task.name)
			finance_task.status = "Open"
			finance_task.progress = 0
			finance_task.completed_by = None
			finance_task.completed_on = None
		app_name = get_application_task(finance_task.project, profile) if finance_task.project else None
		if app_name:
			app = frappe.get_doc("Task", app_name)
			if app.status == "Completed" and _reopen_sea_task(
				app,
				reason=f"Additional {profile.invoice_label} pending Finance payment",
			):
				reopened.append(app_name)
	finally:
		frappe.flags.cgm_reopening_task = False

	return {
		"reopened": reopened,
		"finance_task": finance_task.name,
		"finance_task_url": get_url(f"/app/task/{finance_task.name}"),
	}


@frappe.whitelist()
def reopen_application_task_for_more_documents(task_name: str) -> dict:
	"""Declarant: reopen a completed application task so more invoices/docs can be attached."""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	profile = profile_for_task(task)
	if not profile or not is_application_create_task(task, profile):
		frappe.throw("This action is only for application tasks paired with Finance.")

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import _reopen_sea_task

	reopened: list[str] = []
	frappe.flags.cgm_reopening_task = True
	try:
		if task.status == "Completed" and _reopen_sea_task(
			task,
			reason=f"Additional {profile.invoice_label} / documents after prior completion",
		):
			reopened.append(task.name)
		finance_name = get_application_finance_task(task.project, profile) if task.project else None
		if finance_name:
			finance_task = frappe.get_doc("Task", finance_name)
			# Only reopen Finance when it still has unfinished payment work, or when
			# the application is being opened for a replacement invoice.
			if finance_task.status == "Completed":
				if _reopen_sea_task(
					finance_task,
					reason=f"Application reopened for additional {profile.invoice_label}",
				):
					reopened.append(finance_name)
	finally:
		frappe.flags.cgm_reopening_task = False

	return {
		"task": task_name,
		"status": frappe.db.get_value("Task", task_name, "status"),
		"reopened": reopened,
		"profile": profile.key,
	}


@frappe.whitelist()
def add_amendment_invoice_line(task_name: str, attachment: str | None = None) -> dict:
	"""Declarant: append an additional Invoice line (does not replace the first paid invoice).

	Creates matching rows on the application and finance tasks, reopens both if needed,
	and notifies Finance.
	"""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	profile = profile_for_task(task)
	if not profile or not is_application_create_task(task, profile):
		frappe.throw("Add amendment invoice is only for application tasks paired with Finance.")
	if not task.project:
		frappe.throw("Task must be linked to a Project.")

	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		LINE_INVOICE,
		TASK_FINANCE_FIELD,
		get_invoice_lines,
		task_has_finance_table,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.clearance_charge_item import (
		build_finance_line_payload,
		get_charge_item_label,
		get_clearance_charge_item,
		payment_kind_allows_amendment,
		task_finance_line_has_charge_item,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_purchase_item_for_payment_item,
		task_finance_line_has_item_code,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import _reopen_sea_task

	if not task_has_finance_table(task):
		frappe.throw("This task has no finance lines table.")

	if not payment_kind_allows_amendment(profile.payment_item):
		frappe.throw(
			frappe._(
				"Amendment invoices are not enabled for {0}. "
				"Turn on <b>Allows Amendment Invoices</b> on the Clearance Charge Item."
			).format(profile.invoice_label)
		)

	existing = get_invoice_lines(task, profile)
	amend_no = sum(1 for r in existing if cint(r.get("is_amendment"))) + 1
	charge_item = get_clearance_charge_item(
		profile.payment_item,
		LINE_INVOICE,
		fallback_label=profile.invoice_label,
	)
	base_label = get_charge_item_label(charge_item, profile.invoice_label) or profile.invoice_label
	label = f"{base_label} (amendment {amend_no})"
	payload = build_finance_line_payload(
		LINE_INVOICE,
		profile.payment_item,
		fallback_label=base_label,
		company=task.company,
	)
	payload.update(
		{
			"line_label": label,
			"is_amendment": 1,
			"verified": 0,
		}
	)
	if charge_item and task_finance_line_has_charge_item():
		payload["charge_item"] = charge_item
	if attachment:
		payload["attachment"] = attachment
	if task_finance_line_has_item_code() and not payload.get("item_code"):
		payload["item_code"] = get_purchase_item_for_payment_item(
			profile.payment_item, task.company
		)

	frappe.flags.cgm_reopening_task = True
	reopened: list[str] = []
	try:
		if task.status == "Completed" and _reopen_sea_task(
			task, reason=f"Additional {profile.invoice_label} amendment added"
		):
			reopened.append(task.name)
			task.reload()

		# Clear legacy task-level verified so Create cannot auto-complete again
		# until Finance verifies the new amendment line.
		if profile.application_invoice_verified_field and task.meta.has_field(
			profile.application_invoice_verified_field
		):
			setattr(task, profile.application_invoice_verified_field, 0)
		if profile.application_submitted_field and task.meta.has_field(
			profile.application_submitted_field
		):
			setattr(task, profile.application_submitted_field, 0)

		task.append(TASK_FINANCE_FIELD, payload)
		task.flags.ignore_links = True
		try:
			task.save(ignore_permissions=True)
		finally:
			task.flags.ignore_links = False
		task.reload()
		# Defend against any hook that flipped status back during save.
		if task.status == "Completed":
			_reopen_sea_task(
				task, reason=f"Keep open for {profile.invoice_label} amendment"
			)
			task.reload()

		finance_name = get_application_finance_task(task.project, profile)
		if not finance_name:
			frappe.throw("Paired Finance task not found.")
		finance_task = frappe.get_doc("Task", finance_name)
		if finance_task.status == "Completed" and _reopen_sea_task(
			finance_task,
			reason=f"Additional {profile.invoice_label} amendment needs verify and pay",
		):
			reopened.append(finance_name)
			finance_task.reload()

		if profile.application_invoice_verified_field and finance_task.meta.has_field(
			profile.application_invoice_verified_field
		):
			setattr(finance_task, profile.application_invoice_verified_field, 0)

		# Single sync path (match-by-label/attachment) — never blind-append, or
		# auto_submit/copy can create a duplicate Finance amendment row.
		_sync_changed_application_invoice_onto_finance(task, finance_task, profile)
		finance_task.reload()
		_dedupe_finance_invoice_lines(finance_task, profile)
		finance_task.reload()
		if finance_task.status == "Completed":
			_reopen_sea_task(
				finance_task,
				reason=f"Keep Finance open for {profile.invoice_label} amendment",
			)
			if finance_name not in reopened:
				reopened.append(finance_name)

		notify_result = send_notification(
			profile.notification_invoice,
			finance_task,
			audience=FINANCE_AUDIENCE,
		)
	finally:
		frappe.flags.cgm_reopening_task = False

	return {
		"task": task_name,
		"finance_task": finance_name,
		"line_label": label,
		"reopened": reopened,
		**notify_result,
		"message": workflow_notify_message(
			(
				f"Added <b>{label}</b>"
				+ (f" with attachment" if attachment else "")
				+ f". Finance will verify and pay on <b>{finance_name}</b>."
			),
			notify_result,
			audience=FINANCE_AUDIENCE,
		),
	}


def _dedupe_finance_invoice_lines(finance_task, profile: ApplicationFinanceProfile) -> bool:
	"""Remove duplicate amendment Invoice rows (same label + attachment).

	Keeps the strongest row (verified, then journal entry, then earliest idx).
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		get_invoice_lines,
	)

	rows = list(get_invoice_lines(finance_task, profile))
	groups: dict[tuple, list] = {}
	for row in rows:
		if not cint(row.get("is_amendment")):
			continue
		key = (
			(row.get("line_label") or "").strip(),
			_normalize_attachment_path(row.get("attachment")),
		)
		if not key[1]:
			continue
		groups.setdefault(key, []).append(row)

	removed = False
	for group in groups.values():
		if len(group) < 2:
			continue
		group.sort(
			key=lambda r: (
				cint(r.get("verified")),
				1 if r.get("journal_entry") else 0,
				-(cint(r.get("idx")) or 0),
			),
			reverse=True,
		)
		for row in group[1:]:
			finance_task.remove(row)
			removed = True
	if not removed:
		return False
	finance_task.flags.ignore_links = True
	try:
		finance_task.save(ignore_permissions=True)
	finally:
		finance_task.flags.ignore_links = False
	return True


def _normalize_attachment_path(value) -> str:
	path = (value or "").strip()
	if not path:
		return ""
	# Strip host /private vs /files differences for matching.
	for prefix in ("/private/files/", "/files/"):
		if prefix in path:
			return path.split(prefix, 1)[-1].split("?", 1)[0]
	return path.rsplit("/", 1)[-1].split("?", 1)[0]


def _sync_changed_application_invoice_onto_finance(
	application_task, finance_task, profile: ApplicationFinanceProfile
) -> bool:
	"""Push new/changed application Invoice lines onto finance (primary + amendments)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		LINE_INVOICE,
		TASK_FINANCE_FIELD,
		_match_finance_invoice_line,
		_sync_purchase_item_from_application_line,
		get_invoice_lines,
	)

	app_lines = [r for r in get_invoice_lines(application_task, profile) if r.get("attachment")]
	if not app_lines:
		return False

	fin_lines = list(get_invoice_lines(finance_task, profile))
	used: set[int] = set()
	changed = False

	for app_line in app_lines:
		idx, fin_line = _match_finance_invoice_line(fin_lines, app_line, used)
		if fin_line is None:
			payload = {
				"line_label": app_line.get("line_label") or profile.invoice_label,
				"line_type": LINE_INVOICE,
				"payment_item": profile.payment_item,
				"is_amendment": cint(app_line.get("is_amendment")),
				"attachment": app_line.attachment,
				"verified": 0,
			}
			if app_line.get("charge_item"):
				payload["charge_item"] = app_line.charge_item
			if app_line.get("item_code"):
				payload["item_code"] = app_line.item_code
			finance_task.append(TASK_FINANCE_FIELD, payload)
			fin_lines = list(get_invoice_lines(finance_task, profile))
			changed = True
			continue

		used.add(idx)
		attachment_changed = bool(
			app_line.attachment and fin_line.attachment != app_line.attachment
		)
		if attachment_changed:
			fin_line.attachment = app_line.attachment
			fin_line.verified = 0
			changed = True
			if (
				not cint(app_line.get("is_amendment"))
				and profile.application_invoice_verified_field
				and finance_task.meta.has_field(profile.application_invoice_verified_field)
			):
				setattr(finance_task, profile.application_invoice_verified_field, 0)
		elif not fin_line.attachment and app_line.attachment:
			fin_line.attachment = app_line.attachment
			changed = True

		# Align labels for amendments.
		if app_line.get("line_label") and fin_line.get("line_label") != app_line.line_label:
			fin_line.line_label = app_line.line_label
			changed = True

		if app_line.get("charge_item") and fin_line.get("charge_item") != app_line.charge_item:
			fin_line.charge_item = app_line.charge_item
			changed = True

		# Purchase item: only before this line has a JE.
		if not fin_line.get("journal_entry"):
			if _sync_purchase_item_from_application_line(
				fin_line, app_line, finance_task, profile.payment_item
			):
				changed = True

	if not changed:
		return False

	finance_task.flags.ignore_links = True
	try:
		finance_task.save(ignore_permissions=True)
	finally:
		finance_task.flags.ignore_links = False
	return True


def handle_additional_application_work_on_application(
	application_task, profile: ApplicationFinanceProfile
) -> dict | None:
	"""When Declarant adds/changes an invoice after completion, reopen Finance to verify and pay."""
	if frappe.flags.get("cgm_reopening_task") or frappe.flags.get("cgm_auto_completing_sea_task"):
		return None
	if not is_application_create_task(application_task, profile) or not application_task.project:
		return None
	if application_task.status == "Cancelled":
		return None
	if not invoice_attached(application_task, profile):
		return None
	# Skip when invoice/receipt state did not change on this save.
	if application_task.get_doc_before_save() and not application_invoice_work_changed(
		application_task, profile
	):
		return None

	finance_name = get_application_finance_task(application_task.project, profile)
	if not finance_name:
		return None

	finance_task = frappe.get_doc("Task", finance_name)
	_sync_changed_application_invoice_onto_finance(application_task, finance_task, profile)
	finance_task.reload()

	if not application_finance_needs_work(finance_task, profile):
		return None

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import _reopen_sea_task

	reopened: list[str] = []
	frappe.flags.cgm_reopening_task = True
	try:
		if _reopen_sea_task(
			finance_task,
			reason=f"Additional {profile.invoice_label} needs verification and payment",
		):
			reopened.append(finance_name)
			finance_task.reload()
		if application_task.status == "Completed" and _reopen_sea_task(
			application_task,
			reason=f"Additional {profile.invoice_label} / documents added after prior completion",
		):
			reopened.append(application_task.name)
			application_task.status = "Open"
			application_task.progress = 0
			application_task.completed_by = None
			application_task.completed_on = None
	finally:
		frappe.flags.cgm_reopening_task = False

	# Allow a fresh finance notification when work was reopened after prior submit.
	if (
		reopened
		and profile.application_submitted_field
		and application_task.meta.has_field(profile.application_submitted_field)
		and application_task.get(profile.application_submitted_field)
	):
		frappe.db.set_value(
			"Task",
			application_task.name,
			profile.application_submitted_field,
			0,
			update_modified=False,
		)
		setattr(application_task, profile.application_submitted_field, 0)

	notify_result = {"notified": 0}
	if reopened or not invoice_submitted(application_task.name, profile):
		notify_result = send_notification(
			profile.notification_invoice,
			finance_task,
			audience=FINANCE_AUDIENCE,
		)
		if profile.application_submitted_field and application_task.meta.has_field(
			profile.application_submitted_field
		):
			frappe.db.set_value(
				"Task",
				application_task.name,
				profile.application_submitted_field,
				1,
				update_modified=False,
			)
			setattr(application_task, profile.application_submitted_field, 1)

	return {
		"reopened": reopened,
		"finance_task": finance_name,
		"finance_task_url": get_url(f"/app/task/{finance_name}"),
		**notify_result,
		"message": workflow_notify_message(
			(
				f"Additional {profile.invoice_label} work reopened "
				f"<b>{', '.join(reopened) or finance_name}</b> for verify and pay."
			),
			notify_result,
			audience=FINANCE_AUDIENCE,
		),
	}


def process_application_workflow_on_update(task) -> None:
	"""Run auto-submit, receipt sync, and auto-complete for all configured profiles."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		task_matches_application,
		task_matches_application_finance,
	)

	profile = profile_for_task(task)
	if not profile:
		return
	if task_matches_application(task, profile) and task.status != "Cancelled":
		# Even when Completed: new/changed invoices reopen Finance for verify + pay.
		handle_additional_application_work_on_application(task, profile)
		# Skip first-invoice auto-submit while reopening / adding an amendment —
		# those flows sync + notify themselves (avoids duplicate Finance invoice rows).
		if task.status not in ("Completed", "Cancelled") and not frappe.flags.get(
			"cgm_reopening_task"
		):
			# Same amendment can land twice via attach + sync; keep the strongest row.
			if _dedupe_finance_invoice_lines(task, profile):
				task.reload()
			auto_submit_application_invoice_to_finance_if_needed(task, profile)
			from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
				sync_application_purchase_item_to_finance,
			)

			sync_application_purchase_item_to_finance(task, profile)
			handle_application_receipt_upload(task, profile)
			try_auto_complete_application_task(task, profile)
	elif task_matches_application_finance(task, profile) and task.status != "Cancelled":
		work_changed = application_invoice_work_changed(task, profile)
		# POP / receipt mirror when finance lines actually changed.
		if work_changed:
			if profile.requires_pop:
				from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
					copy_finance_pop_to_application_task,
				)

				copy_finance_pop_to_application_task(task, profile)
			handle_finance_receipt_upload(task, profile)
		# Reopen Completed finance when verify/pay/receipt still outstanding.
		if task.status == "Completed":
			reopen_application_finance_if_pending_work(task, profile)
		else:
			# Clean accidental duplicate amendment rows from earlier double-sync.
			if _dedupe_finance_invoice_lines(task, profile):
				task.reload()
			completed = try_auto_complete_application_finance_task(task, profile)
			if completed:
				close_application_when_finance_done(task, profile)


def process_application_workflow_onload(task) -> bool:
	"""Seed lines, sync status, auto-complete on form open. Returns True if task was updated."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		task_matches_application,
		task_matches_application_finance,
	)

	profile = profile_for_task(task)
	if not profile:
		return False
	changed = ensure_application_finance_lines_saved(task, profile)
	# Seed-save can race with a prior set_value(Completed); re-read status.
	if changed and task.name:
		db_status = frappe.db.get_value("Task", task.name, "status")
		if db_status and task.status != db_status:
			task.reload()
	if task_matches_application_finance(task, profile):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			backfill_legacy_payment_onto_invoice_lines,
		)

		if backfill_legacy_payment_onto_invoice_lines(task, profile):
			from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
				sync_finance_line_payments_to_application_task,
			)

			sync_finance_line_payments_to_application_task(task, profile)
			task.reload()
			changed = True
	if task_matches_application(task, profile):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			ensure_finance_pop_visible_on_application_task,
			ensure_finance_receipt_visible_on_application_task,
		)

		changed = sync_status_from_finance_to_application(task, profile) or changed
		if ensure_finance_pop_visible_on_application_task(task, profile):
			task.reload()
			changed = True
		if ensure_finance_receipt_visible_on_application_task(task, profile):
			task.reload()
			changed = True
		# Heal early Completes (e.g. Shipping Line before receipt verify).
		# Bump modified so a stale Desk form still holding status=Completed cannot
		# save over this heal. Publish soft_sync so an already-open form updates
		# status + modified without a full reload loop.
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			application_has_pending_amendment_invoice,
		)

		needs_reopen = task.status == "Completed" and (
			not can_complete_application_task(task, profile)
			or application_has_pending_amendment_invoice(task, profile)
			or (profile.requires_pop and not can_complete_application_task(task, profile))
		)
		if needs_reopen:
			frappe.flags.cgm_reopening_task = True
			try:
				values = {
					"status": "Open",
					"progress": 0,
					"completed_by": None,
					"completed_on": None,
				}
				frappe.db.set_value("Task", task.name, values, update_modified=True)
				for field, value in values.items():
					task.set(field, value)
				# Keep in-memory modified aligned with DB for the getdoc response.
				task.modified = frappe.db.get_value("Task", task.name, "modified")
				frappe.clear_document_cache("Task", task.name)
				if task.project:
					frappe.publish_realtime(
						"cgm_task_status_changed",
						{
							"task": task.name,
							"project": task.project,
							"status": "Open",
							"reopened": 1,
							"soft_sync": 1,
						},
					)
				changed = True
			finally:
				frappe.flags.cgm_reopening_task = False
		# Do not auto-complete on form open for POP flows — save/verify hooks own that.
		# Completing here raced with heal reopen and flickered the form.
		if (
			task.status not in ("Completed", "Cancelled")
			and not profile.requires_pop
			and try_auto_complete_application_task(task, profile)
		):
			changed = True
	elif task_matches_application_finance(task, profile):
		# Completed + unfinished invoice work → reopen so Make Payment shows.
		result = reopen_application_finance_if_pending_work(task, profile)
		if result and result.get("reopened"):
			task.reload()
			changed = True
		# Remove accidental duplicate amendment rows (same label + attachment).
		if _dedupe_finance_invoice_lines(task, profile):
			task.reload()
			changed = True
		if task.status not in ("Completed", "Cancelled") and task.project:
			if profile.requires_pop:
				from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
					copy_finance_pop_to_application_task,
				)

				if copy_finance_pop_to_application_task(task, profile):
					changed = True
			had_receipt = receipt_attached(task, profile)
			if ensure_application_receipt_on_finance_task(task, profile) and not had_receipt:
				task.reload()
				changed = True
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
			"Finance verifies the invoice, then either records payment (Journal Entry) "
			"or ticks <b>Client will pay</b>. Receipt attachment is optional."
		)


def enforce_kpa_finance_gate(project: str) -> None:
	profile = APPLICATION_FINANCE_PROFILES["KPA Application"]
	finance_task_name = get_application_finance_task(project, profile)
	if not finance_task_name:
		frappe.throw(
			"Generate the sea task plan and complete <b>Finance pays KPA Invoice</b> first."
		)
	finance_task = frappe.get_doc("Task", finance_task_name)
	if finance_task.status != "Completed" or not can_complete_application_finance_task(
		finance_task, profile
	):
		frappe.throw(
			"Cannot move to <b>KPA Paid</b> until <b>Finance pays KPA Invoice</b> is completed: "
			"Finance verifies the invoice, then either records payment (Journal Entry) "
			"or ticks <b>Client will pay</b>. Receipt attachment is optional."
		)
