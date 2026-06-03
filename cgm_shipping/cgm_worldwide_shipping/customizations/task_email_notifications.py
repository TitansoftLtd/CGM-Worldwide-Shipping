"""Email + in-app notifications for sea clearance workflow handoffs."""
from __future__ import annotations

import frappe
from frappe.utils import get_url

FINANCE_ROLES = ("Finance Manager", "Finance User", "Accounts User", "Accounts Manager")
OPERATIONS_ROLES = (
	"Operations Manager",
	"Operations User",
	"Declaration User",
	"Declarant",
	"System Manager",
)

DEFAULT_EMAIL_TEMPLATE = (
	"<p>Hello,</p>"
	"<p>{{ message }}</p>"
	"<p>"
	'<a href="{{ task_url }}">Open task</a>'
	"{% if project_url %} · <a href=\"{{ project_url }}\">Open project</a>{% endif %}"
	"</p>"
)


def get_users_with_roles(roles: tuple[str, ...]) -> list[str]:
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


def get_user_email_addresses(users: list[str]) -> list[str]:
	emails: list[str] = []
	seen: set[str] = set()
	for user in users:
		email = (frappe.db.get_value("User", user, "email") or user or "").strip()
		if not email or "@" not in email or email in seen:
			continue
		seen.add(email)
		emails.append(email)
	return emails


def _notification_exists(task_name: str, subject: str) -> bool:
	return bool(
		frappe.db.exists(
			"Notification Log",
			{"document_type": "Task", "document_name": task_name, "subject": subject},
		)
	)


def _attachments_from_urls(file_urls: list[str] | None) -> list[dict]:
	attachments: list[dict] = []
	for url in file_urls or []:
		if not url:
			continue
		try:
			file_doc = frappe.get_doc("File", {"file_url": url})
			content = file_doc.get_content()
			attachments.append({"fname": file_doc.file_name or url.split("/")[-1], "fcontent": content})
		except Exception:
			frappe.log_error(
				title="CGM workflow email attachment skipped",
				message=f"Could not attach file: {url}",
			)
	return attachments


def send_workflow_task_notification(
	task,
	*,
	subject: str,
	message: str,
	roles: tuple[str, ...],
	email_template: str | None = None,
	attachment_urls: list[str] | None = None,
) -> dict:
	"""
	Notify users by role: in-app Notification Log + email (immediate send).

	Returns counts so the UI can confirm delivery.
	"""
	if _notification_exists(task.name, subject):
		return {
			"notified": 0,
			"emails_sent": 0,
			"email_recipients": [],
			"skipped_duplicate": 1,
		}

	users = get_users_with_roles(roles)
	email_recipients = get_user_email_addresses(users)
	task_url = get_url(f"/app/task/{task.name}")
	project_url = get_url(f"/app/project/{task.project}") if task.project else ""

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

	emails_sent = 0
	email_error = None
	if email_recipients and email_template:
		try:
			frappe.sendmail(
				recipients=email_recipients,
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
				reference_doctype="Task",
				reference_name=task.name,
				attachments=_attachments_from_urls(attachment_urls),
				delayed=False,
				now=True,
			)
			emails_sent = len(email_recipients)
		except Exception as exc:
			email_error = str(exc)
			frappe.log_error(
				title="CGM workflow email failed",
				message=f"Task {task.name}: {subject}\n{exc}",
			)

	return {
		"notified": len(users),
		"emails_sent": emails_sent,
		"email_recipients": email_recipients,
		"email_error": email_error,
	}


def notify_finance_for_task_email(task_name: str, *, action_label: str = "Payment action needed") -> dict:
	"""Notify Finance users (in-app + email) for a payable task."""
	if not task_name or not frappe.db.exists("Task", task_name):
		return {"notified": 0, "emails_sent": 0}

	task = frappe.get_doc("Task", task_name)
	subject = f"{action_label} — {task.project or task.name}"
	message = (
		f"<p>Finance action is required on task <b>{task.subject}</b> ({task.name})"
		f" for project <b>{task.project or '—'}</b>.</p>"
		f"<p>Open the task to create Purchase Invoice / Payment Entry or verify documents.</p>"
	)
	result = send_workflow_task_notification(
		task,
		subject=subject,
		message=message,
		roles=FINANCE_ROLES,
		email_template=DEFAULT_EMAIL_TEMPLATE,
	)
	result["message"] = (
		f"Finance notified ({result.get('emails_sent', 0)} email(s))."
		if result.get("emails_sent")
		else "Finance notified in-app."
	)
	if result.get("email_error"):
		result["message"] += f" Email could not be sent: {result['email_error']}"
	return result


def workflow_notify_message(base: str, result: dict, *, audience: str = "users") -> str:
	if result.get("emails_sent"):
		return f"{base} ({result['emails_sent']} email(s) sent to {audience})."
	if result.get("email_error"):
		return f"{base} In-app alert sent; email failed: {result['email_error']}"
	return f"{base} In-app alert sent."
