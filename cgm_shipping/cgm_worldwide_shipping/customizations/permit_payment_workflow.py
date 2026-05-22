"""Permit invoice → Finance → Payment → Operations receipt → Finance verify → Complete."""
from __future__ import annotations

import frappe
from frappe.utils import get_url, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
	PERMIT_STAGE_BY_TASK_SEQ,
	SEA_PERMIT_APPLICATION_TASK_SEQS,
	TASK_PERMITS_FIELD,
	sync_task_permits_to_project,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import SEA_TASK_FLOW_KEY

FINANCE_ROLES = ("Finance Manager", "Accounts User", "Accounts Manager")
OPERATIONS_ROLES = (
	"Operations Manager",
	"Operations User",
	"Declaration User",
	"Declarant",
	"System Manager",
)


def _users_with_roles(roles: tuple[str, ...]) -> list[str]:
	seen: set[str] = set()
	out: list[str] = []
	for role in roles:
		for user in frappe.get_all(
			"Has Role",
			filters={"role": role, "parenttype": "User"},
			pluck="parent",
		):
			if user in seen or not frappe.db.get_value("User", user, "enabled"):
				continue
			seen.add(user)
			out.append(user)
	return out


def _notification_exists(task_name: str, subject: str) -> bool:
	return bool(
		frappe.db.exists(
			"Notification Log",
			{"document_type": "Task", "document_name": task_name, "subject": subject},
		)
	)


def _send_task_notifications(
	task,
	*,
	subject: str,
	message: str,
	roles: tuple[str, ...],
	email_template: str | None = None,
) -> int:
	if _notification_exists(task.name, subject):
		return 0

	users = _users_with_roles(roles)
	task_url = get_url(f"/app/task/{task.name}")
	project_url = get_url(f"/app/project/{task.project}") if task.project else ""

	count = 0
	for user in users:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"from_user": frappe.session.user,
				"document_type": "Task",
				"document_name": task.name,
				"subject": subject,
				"email_content": message,
			}
		).insert(ignore_permissions=True)
		count += 1

	if users and email_template:
		try:
			frappe.sendmail(
				recipients=users,
				subject=subject,
				message=frappe.render_template(
					email_template,
					{
						"task": task,
						"task_url": task_url,
						"project_url": project_url,
						"project": task.project,
						"message": message,
					},
				),
			)
		except Exception:
			frappe.log_error(title="CGM permit notification email failed")

	return count


def all_permit_rows_have_invoices(task) -> bool:
	rows = task.get(TASK_PERMITS_FIELD) or []
	return bool(rows) and all(r.permit_type and r.get("payment_invoice") for r in rows)


def permit_invoices_ready(task_name: str) -> bool:
	if not task_name or not frappe.db.exists("Task", task_name):
		return False
	if frappe.db.get_value("Task", task_name, "custom_permit_invoices_submitted"):
		return True
	task = frappe.get_doc("Task", task_name)
	return all_permit_rows_have_invoices(task)


def permit_invoices_ready_for_project(project: str, stage: str = "Pre-clearance") -> bool:
	"""True when application task (5 or 15) has all permit invoices submitted to Finance."""
	for seq in (5, 15):
		task_name = frappe.db.get_value(
			"Task",
			{
				"project": project,
				"custom_task_flow_key": SEA_TASK_FLOW_KEY,
				"custom_sequence_no": seq,
			},
			"name",
		)
		if not task_name:
			continue
		task_stage = PERMIT_STAGE_BY_TASK_SEQ.get(seq)
		if task_stage != stage:
			continue
		if permit_invoices_ready(task_name):
			return True
	return False


def get_permit_application_task(project: str, seq: int) -> str | None:
	return frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": seq,
		},
		"name",
	)


@frappe.whitelist()
def submit_permit_invoices_to_finance(task_name: str) -> dict:
	"""Declaration submits permit invoices — notify Finance; task stays Open."""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	seq = int(task.get("custom_sequence_no") or 0)
	if seq not in SEA_PERMIT_APPLICATION_TASK_SEQS:
		frappe.throw("This action is only for permit application tasks (5 and 15).")

	if not all_permit_rows_have_invoices(task):
		frappe.throw(
			"Attach <b>Permit Invoice (for Finance)</b> on every row in <b>Task Permits</b> first."
		)

	sync_task_permits_to_project(task)
	task.custom_permit_invoices_submitted = 1
	task.save(ignore_permissions=True)

	permit_types = ", ".join(r.permit_type for r in task.get(TASK_PERMITS_FIELD) or [] if r.permit_type)
	subject = f"Permit invoices ready for review — {task.project or task.name}"
	message = (
		f"<p>Permit invoices are ready on task <b>{task.subject}</b> "
		f"({task.name}) for project <b>{task.project}</b>.</p>"
		f"<p>Permits: {permit_types}</p>"
		f"<p>Review invoices on the task or <b>Project → Regulatory Permits</b>, "
		f"then open <b>Finance pays Pre-Clearance Permits</b> to process payment.</p>"
	)

	notified = _send_task_notifications(
		task,
		subject=subject,
		message=message,
		roles=FINANCE_ROLES,
		email_template=(
			"<p>Hello,</p><p>{{ message }}</p>"
			"<p><a href=\"{{ task_url }}\">Open task</a> · "
			"<a href=\"{{ project_url }}\">Open project</a></p>"
		),
	)

	return {
		"task": task.name,
		"status": task.status,
		"notified": notified,
		"message": "Finance notified. Task stays open until payment and receipts are verified on the finance task.",
	}


def notify_operations_upload_receipts(task) -> dict:
	"""After Finance submits payment — ask Operations to upload receipts on Task 6."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != 6 or not task.get("custom_payment_entry"):
		return {"notified": 0}

	subject = f"Upload permit payment receipts — {task.project or task.name}"
	message = (
		f"<p>Payment was recorded for <b>{task.subject}</b> ({task.name}).</p>"
		f"<p>Upload <b>Payment Receipt</b> on each permit row on this task "
		f"(or on <b>Project → Regulatory Permits</b>).</p>"
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
def notify_finance_verify_receipts(task_name: str) -> dict:
	"""Called when Operations uploads a payment receipt on Task 6."""
	if not task_name or not frappe.db.exists("Task", task_name):
		return {"notified": 0}
	task = frappe.get_doc("Task", task_name)
	return _notify_finance_verify_receipts(task)


def _notify_finance_verify_receipts(task) -> dict:
	"""Operations uploaded receipts — Finance must verify before task can close."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != 6:
		return {"notified": 0}

	rows = task.get(TASK_PERMITS_FIELD) or []
	if not any(r.get("payment_receipt") for r in rows):
		return {"notified": 0}

	subject = f"Verify permit payment receipts — {task.project or task.name}"
	message = (
		f"<p>Payment receipts were uploaded for <b>{task.project}</b>.</p>"
		f"<p>Verify each receipt on task <b>{task.name}</b> and tick "
		f"<b>Receipt Verified</b> before completing the finance task.</p>"
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


def seed_finance_task_permits_from_project(task) -> None:
	"""Copy Project permit rows onto Task 6 for receipt upload / verification."""
	if int(task.get("custom_sequence_no") or 0) != 6:
		return
	if not task.meta.has_field(TASK_PERMITS_FIELD) or not task.project:
		return
	if task.get(TASK_PERMITS_FIELD):
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.project import PERMIT_REGISTER_FIELD

	project = frappe.get_doc("Project", task.project)
	for row in project.get(PERMIT_REGISTER_FIELD) or []:
		if row.stage != "Pre-clearance" or not row.permit_type:
			continue
		task.append(
			TASK_PERMITS_FIELD,
			{
				"permit_type": row.permit_type,
				"stage": row.stage,
				"payment_invoice": row.get("payment_invoice"),
				"invoice_amount": row.get("invoice_amount"),
				"purchase_invoice": row.get("purchase_invoice"),
				"payment_entry": row.get("payment_entry"),
				"payment_receipt": row.get("payment_receipt"),
				"receipt_verified": row.get("receipt_verified"),
				"status": row.get("status"),
			},
		)


def validate_finance_permit_payment_task(task) -> None:
	"""Task 6 / 15 finance: PI + PE + ops receipts + finance verification."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq not in (6,):  # post-clearance finance could be extended later
		return

	app_seq = 5 if seq == 6 else 15
	app_task = get_permit_application_task(task.project, app_seq)
	if app_task and not permit_invoices_ready(app_task):
		frappe.throw(
			"Permit invoices must be submitted to Finance from the "
			"<b>Apply for Pre-Clearance Permits</b> task first."
		)

	rows = task.get(TASK_PERMITS_FIELD) or []
	if not rows:
		frappe.throw(
			"Open this task after permit invoices are on the Project, or refresh the page "
			"to load <b>Task Permits</b>."
		)

	missing_receipts = [r.permit_type for r in rows if r.permit_type and not r.get("payment_receipt")]
	if missing_receipts:
		frappe.throw(
			"Operations must upload <b>Payment Receipt</b> for each permit before this task "
			f"can be completed. Missing: "
			f"<b>{', '.join(missing_receipts)}</b>."
		)

	unverified = [r.permit_type for r in rows if r.permit_type and not r.get("receipt_verified")]
	if unverified:
		frappe.throw(
			"Finance must tick <b>Receipt Verified</b> on every permit row before completing. "
			f"Pending: <b>{', '.join(unverified)}</b>."
		)


def validate_permit_application_not_completed(task) -> None:
	"""Tasks 5/15 cannot be marked Completed manually — close when finance task finishes."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq not in SEA_PERMIT_APPLICATION_TASK_SEQS:
		return
	frappe.throw(
		"This task cannot be marked Completed here. Use <b>Notify Finance — invoices ready</b>, "
		"then complete the matching <b>Finance pays … Permits</b> task after payment and "
		"receipt verification."
	)


def enforce_receipt_verified_permission(task) -> None:
	"""Only Finance may tick Receipt Verified on permit payment tasks."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != 6:
		return
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles())
	if set(FINANCE_ROLES) & roles:
		return
	for row in task.get(TASK_PERMITS_FIELD) or []:
		if row.get("receipt_verified"):
			frappe.throw("Only <b>Finance</b> can mark <b>Receipt Verified</b> on permit rows.")


def close_permit_application_when_finance_done(task) -> None:
	"""When finance permit task completes, close the open application task (5 or 15)."""
	seq = int(task.get("custom_sequence_no") or 0)
	if seq != 6 or task.status != "Completed":
		return
	app_name = get_permit_application_task(task.project, 5)
	if not app_name:
		return
	if frappe.db.get_value("Task", app_name, "status") == "Completed":
		return
	app = frappe.get_doc("Task", app_name)
	app.status = "Completed"
	app.completed_by = task.completed_by
	app.completed_on = task.completed_on or now_datetime()
	app.description = (
		"Permit invoices submitted to Finance; payment and receipt verification "
		f"completed on {task.name}."
	)
	frappe.flags.cgm_auto_completing_sea_task = True
	try:
		app.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_auto_completing_sea_task = False
