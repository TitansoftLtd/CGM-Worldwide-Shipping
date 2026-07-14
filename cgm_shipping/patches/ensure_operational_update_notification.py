"""Ensure Notification for generic operational Update DocType."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	OPERATIONAL_UPDATE_NOTIFICATION,
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
	notification.message = (
		"<p>A new operational update was posted.</p>"
		"<p><b>Source:</b> {{ doc.update_source }}</p>"
		"<p><b>Subject:</b> {{ doc.subject }}</p>"
		"<p><b>Message:</b> {{ doc.message or '—' }}</p>"
		"<p><b>Shipment:</b> {{ doc.project or '—' }}</p>"
	)
	notification.append("recipients", {"receiver_by_role": "Transport Officer"})
	notification.append("recipients", {"receiver_by_role": "Operations Manager"})
	frappe.flags.ignore_links = True
	notification.insert(ignore_permissions=True)
	frappe.db.commit()
