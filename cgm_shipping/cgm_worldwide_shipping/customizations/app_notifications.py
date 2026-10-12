"""Notifications the app's code sends by name, created on migrate when missing.

Only a missing Notification is created. An existing one - its wording,
recipients, and whether it is enabled - stays exactly as the desk has it.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	FINAL_DOCUMENT_NOTIFICATION,
	OPERATIONAL_UPDATE_NOTIFICATION,
	PORTAL_FEEDBACK_NOTIFICATION,
	PORTAL_UPDATE_PUBLISHED_NOTIFICATION,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
	notification_link,
	notification_message,
	notification_paragraph,
	task_notification_message,
)

_SHIPMENT = (
	"{{ doc.get('cgm_shipment_name') "
	"or (frappe.db.get_value('Project', doc.project, 'project_name') if doc.project else None) "
	"or doc.project or '-' }}"
)


def final_document_review_message() -> str:
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


def operational_update_message() -> str:
	return notification_message(
		"A new operational update was posted.",
		(
			("Shipment", "<b>" + _SHIPMENT + "</b>"),
			("Source", "{{ doc.update_source }}"),
			("Subject", "{{ doc.subject }}"),
		),
		extra=notification_paragraph("Update", "{{ doc.message or '-' }}"),
		link=notification_link("Shipment Update", "Open update"),
	)


def portal_update_message() -> str:
	return notification_message(
		"CGM Worldwide Shipping posted an update on your shipment.",
		(
			("Shipment", "<b>" + _SHIPMENT + "</b>"),
			("Container", "{{ doc.container_number or '-' }}"),
			("Subject", "{{ doc.subject }}"),
		),
		extra=notification_paragraph("Update", "{{ doc.message or '-' }}"),
		note="Sign in to the portal to reply to this update.",
	)


def portal_feedback_message() -> str:
	return notification_message(
		"A portal user left feedback.",
		(
			("Shipment", "<b>" + _SHIPMENT + "</b>"),
			("Container", "{{ doc.container_number or '-' }}"),
			("From", "{{ doc.submitted_by_party }}"),
			("Rating", "{{ ((doc.rating or 0) * 5) | round | int }} / 5"),
			("Category", "{{ doc.category or '-' }}"),
		),
		extra=notification_paragraph("Comments", "{{ doc.comments or '-' }}"),
		link=notification_link("Portal Feedback", "Open feedback"),
	)


def _notifications() -> list[dict]:
	return [
		{
			"name": FINAL_DOCUMENT_NOTIFICATION,
			"document_type": "Task",
			"subject": "Final document review required: {{ doc.name }}",
			"message": final_document_review_message(),
			"recipients": [{"receiver_by_document_field": "owner"}],
		},
		{
			"name": OPERATIONAL_UPDATE_NOTIFICATION,
			"document_type": "Shipment Update",
			"subject": "{{ doc.update_source }} update: {{ doc.subject }}",
			"message": operational_update_message(),
			"recipients": [
				{"receiver_by_role": "Transport Officer"},
				{"receiver_by_role": "Operations Manager"},
			],
		},
		{
			# Recipients are resolved per document (portal users); roles would email staff.
			"name": PORTAL_UPDATE_PUBLISHED_NOTIFICATION,
			"document_type": "Shipment Update",
			"subject": "Update on your shipment: {{ doc.subject }}",
			"message": portal_update_message(),
			"recipients": [],
		},
		{
			"name": PORTAL_FEEDBACK_NOTIFICATION,
			"document_type": "Portal Feedback",
			"subject": "{{ doc.submitted_by_party }} feedback: {{ doc.category or 'Overall Service' }}",
			"message": portal_feedback_message(),
			"recipients": [
				{"receiver_by_role": "Operations Manager"},
				{"receiver_by_role": "Transport Officer"},
			],
		},
	]


def ensure_app_notifications() -> None:
	if not frappe.db.exists("DocType", "Notification"):
		return
	for spec in _notifications():
		if frappe.db.exists("Notification", spec["name"]):
			continue
		if not frappe.db.exists("DocType", spec["document_type"]):
			continue
		notification = frappe.new_doc("Notification")
		notification.name = spec["name"]
		notification.subject = spec["subject"]
		notification.document_type = spec["document_type"]
		notification.channel = "Email"
		notification.event = "Custom"
		notification.enabled = 1
		notification.message_type = "HTML"
		notification.message = spec["message"]
		for recipient in spec["recipients"]:
			notification.append("recipients", recipient)
		previous = frappe.flags.ignore_links
		frappe.flags.ignore_links = True
		try:
			notification.insert(ignore_permissions=True)
		finally:
			frappe.flags.ignore_links = previous
	frappe.db.commit()
