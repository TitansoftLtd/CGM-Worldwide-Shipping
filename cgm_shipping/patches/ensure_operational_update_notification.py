"""Ensure Notification for generic operational Update DocType."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	OPERATIONAL_UPDATE_NOTIFICATION,
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


def operational_update_message() -> str:
	"""Shared with the sync patch so Desk and code stay on one layout."""
	return notification_message(
		"A new operational update was posted.",
		(
			("Shipment", "<b>" + _SHIPMENT + "</b>"),
			("Source", "{{ doc.update_source }}"),
			("Subject", "{{ doc.subject }}"),
		),
		extra=notification_paragraph("Update", "{{ doc.message or '-' }}"),
		link=notification_link("Update", "Open update"),
	)


def execute() -> None:
	if not frappe.db.exists("DocType", "Notification"):
		return
	if not frappe.db.exists("DocType", "Update"):
		return

	if frappe.db.exists("Notification", OPERATIONAL_UPDATE_NOTIFICATION):
		doc = frappe.get_doc("Notification", OPERATIONAL_UPDATE_NOTIFICATION)
		doc.document_type = "Update"
		doc.enabled = 1
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return

	notification = frappe.new_doc("Notification")
	notification.name = OPERATIONAL_UPDATE_NOTIFICATION
	notification.subject = "{{ doc.update_source }} update: {{ doc.subject }}"
	notification.document_type = "Update"
	notification.channel = "Email"
	notification.event = "Custom"
	notification.enabled = 1
	notification.message_type = "HTML"
	notification.message = operational_update_message()
	notification.append("recipients", {"receiver_by_role": "Transport Officer"})
	notification.append("recipients", {"receiver_by_role": "Operations Manager"})
	frappe.flags.ignore_links = True
	notification.insert(ignore_permissions=True)
	frappe.db.commit()
