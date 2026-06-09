"""One-off: run with bench execute before migrate if CGM Shipment module blocks sync."""
from __future__ import annotations

import frappe

OLD = "CGM Shipment"
NEW = "CGM Worldwide Shipping"

DOCTYPES = (
	"CFS Master",
	"Permit Register",
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


def fix():
	for dt in DOCTYPES:
		if frappe.db.exists("DocType", dt):
			frappe.db.set_value("DocType", dt, "module", NEW, update_modified=False)
	frappe.db.sql(
		"UPDATE `tabCustom Field` SET module = %s WHERE module = %s",
		(NEW, OLD),
	)
	if frappe.db.exists("Workspace", OLD) and frappe.db.exists("Workspace", NEW):
		frappe.delete_doc("Workspace", OLD, force=1)
	if frappe.db.exists("Module Def", OLD):
		frappe.delete_doc("Module Def", OLD, force=1)
	frappe.db.commit()
	print("Module consolidation DB fix applied.")
