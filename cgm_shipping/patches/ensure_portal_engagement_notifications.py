"""Seed the Notifications used by the customer / transporter portal engagement.

Two events need admin-editable templates:

* `CGM Portal - Update Published` - emailed to the portal users of a customer
  or transporter when CGM publishes an update to them. Recipients are worked
  out per-document in `operational_updates.portal_recipients_for_update`, so
  this Notification carries only the wording.
* `CGM Portal - Feedback Received` - emailed to operations when a party rates
  a shipment or a container. Recipients come from the roles on the doc.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	PORTAL_FEEDBACK_NOTIFICATION,
	PORTAL_UPDATE_PUBLISHED_NOTIFICATION,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
	notification_link,
	notification_message,
	notification_paragraph,
)

_SHIPMENT = (
	"{{ doc.get('cgm_shipment_name') "
	"or (frappe.db.get_value('Project', doc.project, 'project_name') if doc.project else None) "
	"or doc.project or '-' }}"
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


def _ensure(name: str, *, document_type: str, subject: str, message: str, roles: tuple[str, ...]):
	if not frappe.db.exists("DocType", document_type):
		return

	if frappe.db.exists("Notification", name):
		doc = frappe.get_doc("Notification", name)
		doc.document_type = document_type
		doc.enabled = 1
		if not (doc.message or "").strip():
			doc.message = message
		doc.save(ignore_permissions=True)
		return

	notification = frappe.new_doc("Notification")
	notification.name = name
	notification.subject = subject
	notification.document_type = document_type
	notification.channel = "Email"
	notification.event = "Custom"
	notification.enabled = 1
	notification.message_type = "HTML"
	notification.message = message
	for role in roles:
		notification.append("recipients", {"receiver_by_role": role})
	frappe.flags.ignore_links = True
	notification.insert(ignore_permissions=True)


def execute() -> None:
	if not frappe.db.exists("DocType", "Notification"):
		return

	_ensure(
		PORTAL_UPDATE_PUBLISHED_NOTIFICATION,
		document_type="Shipment Update",
		subject="Update on your shipment: {{ doc.subject }}",
		message=portal_update_message(),
		# Recipients are resolved per document; roles here would email staff.
		roles=(),
	)
	_ensure(
		PORTAL_FEEDBACK_NOTIFICATION,
		document_type="Portal Feedback",
		subject="{{ doc.submitted_by_party }} feedback: {{ doc.category or 'Overall Service' }}",
		message=portal_feedback_message(),
		roles=("Operations Manager", "Transport Officer"),
	)
	frappe.db.commit()
