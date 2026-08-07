"""Trigger ERPNext Custom notifications; recipients are configured on each Notification doc."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	DAILY_STATUS_RAG_ALERT,
	FINANCE_PAYMENT_ACTION,
	PERMIT_INVOICES_TO_FINANCE,
	PERMIT_RECEIPTS_FOR_DECLARANT,
	PERMIT_RECEIPTS_VERIFY_FINANCE,
	UCR_INVOICE_TO_FINANCE,
	UCR_RECEIPT_FOR_DECLARANT,
	UCR_RECEIPT_VERIFY_FINANCE,
)


@frappe.request_cache
def get_task_form_permissions() -> dict[str, bool]:
	"""Task form UI flags from CGM Shipping Settings document responsibilities."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		responsibility_flags_for_user,
	)

	return responsibility_flags_for_user()


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

	# Prefer shipment business name (e.g. LJL-2606-0635 / 4X40 / 30) over Project ID.
	try:
		from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
			stamp_shipment_name_on_doc,
		)

		stamp_shipment_name_on_doc(doc)
	except Exception:
		pass

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
