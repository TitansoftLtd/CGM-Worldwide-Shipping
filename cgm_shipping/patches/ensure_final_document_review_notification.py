"""Install optional Notification for final document review routing."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	FINAL_DOCUMENT_NOTIFICATION,
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
	notification.message = (
		"<p>A final shipment document has been sent for your review.</p>"
		"<p>{{ doc.cgm_attachment_review_label or doc.cgm_final_document_review_label or 'Open the linked task or project.' }}</p>"
	)
	notification.append("recipients", {"receiver_by_document_field": "owner"})
	frappe.flags.ignore_links = True
	notification.insert(ignore_permissions=True)
	frappe.db.commit()
