"""Trigger ERPNext Custom notifications; recipients are configured on each Notification doc."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.notifications.constants import (
	FINANCE_PAYMENT_ACTION,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.permissions.service import (
	get_user_sea_task_department_stems,
	user_has_finance_department_access,
)


@frappe.request_cache
def get_task_form_permissions() -> dict[str, bool]:
	"""Task form UI flags from ERPNext roles vs sea task template departments."""
	if frappe.session.user == "Administrator":
		return {
			"can_make_payment": True,
			"can_upload_receipt": True,
			"can_record_purchase_invoice": True,
		}

	user = frappe.session.user
	department_stems = get_user_sea_task_department_stems(user)
	can_finance = user_has_finance_department_access(user)

	return {
		"can_make_payment": can_finance,
		"can_upload_receipt": bool(department_stems),
		"can_record_purchase_invoice": can_finance
		or frappe.has_permission("Purchase Invoice", ptype="create"),
	}


def send_notification(notification_name: str, doc, *, audience: str = "users") -> dict:
	"""Fire a Custom Notification using recipients defined on the Notification doc."""
	if not notification_name or not doc:
		return {"notified": 0, "emails_sent": 0}

	if not frappe.db.exists("Notification", notification_name):
		frappe.log_error(
			title="CGM notification missing",
			message=f"Create Notification '{notification_name}' (run bench migrate / import fixtures).",
		)
		return {
			"notified": 0,
			"emails_sent": 0,
			"message": f"Notification <b>{notification_name}</b> is not installed on this site.",
		}

	notification = frappe.get_doc("Notification", notification_name)
	if not notification.enabled:
		return {
			"notified": 0,
			"emails_sent": 0,
			"message": f"Notification <b>{notification_name}</b> is disabled.",
		}

	if not notification.get("recipients") and not notification.send_to_all_assignees:
		return {
			"notified": 0,
			"emails_sent": 0,
			"message": (
				f"Notification <b>{notification_name}</b> has no recipients. "
				"Add roles on the Notification document in Desk."
			),
		}

	recipient_count = len(notification.get("recipients") or [])

	try:
		notification.send(doc)
	except Exception as exc:
		frappe.log_error(title=f"CGM notification failed: {notification_name}", message=str(exc))
		return {
			"notified": 0,
			"emails_sent": 0,
			"email_error": str(exc),
			"message": f"Could not send notification: {exc}",
		}

	notified = 1
	emails_sent = 1 if notification.channel == "Email" else 0

	return {
		"notified": notified,
		"emails_sent": emails_sent,
		"recipient_count": recipient_count,
		"message": workflow_notify_message(
			f"Notification <b>{notification_name}</b> sent.",
			{"notified": notified, "emails_sent": emails_sent, "recipient_count": recipient_count},
			audience=audience,
		),
	}


def notify_finance_for_task(task_name: str, *, action_label: str = "Payment action needed") -> dict:
	if not task_name or not frappe.db.exists("Task", task_name):
		return {"notified": 0, "emails_sent": 0}

	task = frappe.get_doc("Task", task_name)
	task.cgm_notification_action_label = action_label
	return send_notification(FINANCE_PAYMENT_ACTION, task, audience="Finance")


def workflow_notify_message(base: str, result: dict, *, audience: str = "users") -> str:
	if result.get("email_error"):
		return f"{base} Notification failed: {result['email_error']}"
	if not result.get("notified"):
		return f"{base} (no recipients or notification disabled)."
	if result.get("emails_sent"):
		count = result.get("recipient_count") or result.get("emails_sent")
		return f"{base} (alert sent to {count} role(s) for {audience})."
	return f"{base} (in-app alert for {audience}; email not enabled on this notification)."
