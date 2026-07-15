"""Migrate Transporter Truck Update rows into the generic Update DocType."""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "Update"):
		return

	_migrate_rows()
	_migrate_notification()
	_remove_old_doctype()


def _legacy_table_exists() -> bool:
	return bool(frappe.db.sql("SHOW TABLES LIKE %s", ("tabTransporter Truck Update",)))


def _migrate_rows() -> None:
	if not _legacy_table_exists():
		return

	old_rows = frappe.db.sql(
		"""
		SELECT
			name, allocation, allocation_item, project, container_tracker,
			container_number, transporter, update_type, event_date, posted_on,
			posted_by, message, truck_number, driver_name, driver_contact, attachment
		FROM `tabTransporter Truck Update`
		""",
		as_dict=True,
	)
	for row in old_rows:
		if frappe.db.exists("Update", row.name):
			continue
		customer = None
		if row.project:
			customer = frappe.db.get_value("Project", row.project, "customer")
		doc = frappe.get_doc(
			{
				"doctype": "Update",
				"name": row.name,
				"update_source": "Transporter",
				"subject": row.update_type or "Other",
				"message": row.message,
				"posted_on": row.posted_on,
				"posted_by": row.posted_by,
				"is_read": 1,
				"project": row.project,
				"customer": customer,
				"container_tracker": row.container_tracker,
				"container_number": row.container_number,
				"transporter": row.transporter,
				"allocation": row.allocation,
				"allocation_item": row.allocation_item,
				"event_date": row.event_date,
				"truck_number": row.truck_number,
				"driver_name": row.driver_name,
				"driver_contact": row.driver_contact,
				"attachment": row.attachment,
				"related_doctype": "Container Allocation" if row.allocation else None,
				"related_name": row.allocation,
			}
		)
		doc.flags.name_set = True
		doc.insert(ignore_permissions=True)
	frappe.db.commit()


def _migrate_notification() -> None:
	old_name = "CGM Transporter - Truck Update"
	new_name = "CGM Operational Update"
	if not frappe.db.exists("DocType", "Notification"):
		return

	if frappe.db.exists("Notification", old_name) and not frappe.db.exists("Notification", new_name):
		frappe.rename_doc("Notification", old_name, new_name, force=True)

	if frappe.db.exists("Notification", new_name):
		doc = frappe.get_doc("Notification", new_name)
		doc.document_type = "Update"
		doc.enabled = 1
		doc.subject = "{{ doc.update_source }} update: {{ doc.subject }}"
		doc.message = (
			"<p>A new operational update was posted.</p>"
			"<p><b>Source:</b> {{ doc.update_source }}</p>"
			"<p><b>Subject:</b> {{ doc.subject }}</p>"
			"<p><b>Message:</b> {{ doc.message or '—' }}</p>"
			"<p><b>Shipment:</b> {{ doc.project or '—' }}</p>"
		)
		if not doc.get("recipients"):
			doc.append("recipients", {"receiver_by_role": "Transport Officer"})
			doc.append("recipients", {"receiver_by_role": "Operations Manager"})
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return

	notification = frappe.new_doc("Notification")
	notification.name = new_name
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


def _remove_old_doctype() -> None:
	if frappe.db.exists("DocType", "Transporter Truck Update"):
		frappe.delete_doc("DocType", "Transporter Truck Update", force=True, ignore_permissions=True)
		frappe.db.commit()
	# DocType delete can leave the physical table behind when already partially removed.
	# table_exists() can miss names with spaces — use SHOW TABLES.
	if _legacy_table_exists():
		frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabTransporter Truck Update`")
		frappe.db.commit()
