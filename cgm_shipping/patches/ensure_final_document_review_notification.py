"""Install optional Notification for final document review routing."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	FINAL_DOCUMENT_NOTIFICATION,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
	notification_paragraph,
	task_notification_message,
)


def final_document_review_message() -> str:
	"""Shared with the sync patch so Desk and code stay on one layout."""
	return task_notification_message(
		"A final shipment document was sent for your review.",
		"Open the task and review the attached document.",
		"Approve or return it so the shipment can move on.",
		extra=notification_paragraph(
			"Document",
			"{{ doc.cgm_attachment_review_label "
			"or doc.cgm_final_document_review_label or 'See the task attachments.' }}",
		),
	)


def execute() -> None:
	if not frappe.db.exists("DocType", "Notification"):
		return

	if frappe.db.exists("Notification", FINAL_DOCUMENT_NOTIFICATION):
		doc = frappe.get_doc("Notification", FINAL_DOCUMENT_NOTIFICATION)
		doc.enabled = 1
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return

	notification = frappe.new_doc("Notification")
	notification.name = FINAL_DOCUMENT_NOTIFICATION
	notification.subject = "Final document review required: {{ doc.name }}"
	notification.document_type = "Task"
	notification.channel = "Email"
	notification.event = "Custom"
	notification.enabled = 1
	notification.message_type = "HTML"
	notification.message = final_document_review_message()
	notification.append("recipients", {"receiver_by_document_field": "owner"})
	frappe.flags.ignore_links = True
	notification.insert(ignore_permissions=True)
	frappe.db.commit()
