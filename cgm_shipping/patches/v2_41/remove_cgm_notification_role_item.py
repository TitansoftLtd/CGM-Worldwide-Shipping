"""Remove legacy CGM Notification Role Item child table and DocType."""
from __future__ import annotations

import frappe

CHILD_DOCTYPE = "CGM Notification Role Item"
SETTINGS = "CGM Shipping Settings"


def execute():
	_clear_settings_notification_roles()
	_delete_child_rows()
	_delete_doctype()
	frappe.db.commit()
	frappe.clear_cache()


def _clear_settings_notification_roles() -> None:
	"""Drop child rows without loading Settings (controller may be missing)."""
	if not frappe.db.table_exists(f"tab{CHILD_DOCTYPE}"):
		return
	frappe.db.delete(
		CHILD_DOCTYPE,
		{"parent": SETTINGS, "parenttype": SETTINGS, "parentfield": "custom_notification_roles"},
	)


def _delete_child_rows() -> None:
	if not frappe.db.table_exists(f"tab{CHILD_DOCTYPE}"):
		return
	frappe.db.delete(CHILD_DOCTYPE)


def _delete_doctype() -> None:
	if not frappe.db.exists("DocType", CHILD_DOCTYPE):
		return
	frappe.delete_doc("DocType", CHILD_DOCTYPE, force=1, ignore_permissions=True)
