"""Point guide doctypes, custom fields, and workspace at CGM Worldwide Shipping module."""
from __future__ import annotations

import frappe

NEW_MODULE = "CGM Worldwide Shipping"
OLD_MODULE = "CGM Shipment"

GUIDE_DOCTYPES = (
	"CFS Master",
	"Permit Register",
	"Shipment Dossier",
	"IDF UCR Record",
	"Customs Entry",
	"Container Tracker",
	"Daily Status Update",
	"Shipping Line Charges",
	"Port Charges KPA Invoice",
	"Seal Record",
	"Export Shipment",
	"Interchange Receipt",
)


def execute():
	_rehome_doctypes()
	_rehome_custom_fields()
	_rehome_workspace()
	_remove_old_module_def()


def _rehome_doctypes():
	for name in GUIDE_DOCTYPES:
		if frappe.db.exists("DocType", name):
			frappe.db.set_value("DocType", name, "module", NEW_MODULE, update_modified=False)


def _rehome_custom_fields():
	frappe.db.sql(
		"""
		UPDATE `tabCustom Field`
		SET module = %s
		WHERE module = %s
		""",
		(NEW_MODULE, OLD_MODULE),
	)


def _rehome_workspace():
	if frappe.db.exists("Workspace", OLD_MODULE):
		# Avoid name clash: drop old workspace if target already exists
		if frappe.db.exists("Workspace", NEW_MODULE):
			frappe.delete_doc("Workspace", OLD_MODULE, force=1, ignore_permissions=True)
		else:
			frappe.rename_doc("Workspace", OLD_MODULE, NEW_MODULE, force=1)
	elif frappe.db.exists("Workspace", NEW_MODULE):
		frappe.db.set_value("Workspace", NEW_MODULE, "module", NEW_MODULE, update_modified=False)


def _remove_old_module_def():
	if frappe.db.exists("Module Def", OLD_MODULE):
		frappe.delete_doc("Module Def", OLD_MODULE, force=1, ignore_permissions=True)
