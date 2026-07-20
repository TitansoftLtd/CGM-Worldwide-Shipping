"""Repoint legacy MFI Shipping Reports (and related records) to CGM Worldwide Shipping.

Older sites still have Report.module = ``MFI Shipping``. Script reports then resolve to
``frappe.mfi_shipping.report...`` and raise ModuleNotFoundError.
"""

from __future__ import annotations

import frappe

TARGET_MODULE = "CGM Worldwide Shipping"
LEGACY_MODULES = ("mfi_shipping", "MFI Shipping", "Mfi Shipping")

# Desk records that store a ``module`` field and must match the app package path.
_DOCTYPE_TABLES = (
	"Report",
	"Page",
	"Workspace",
	"Dashboard",
	"Dashboard Chart",
	"Number Card",
	"Print Format",
	"Web Form",
	"Web Page",
)


def execute() -> None:
	for doctype in _DOCTYPE_TABLES:
		if not frappe.db.table_exists(doctype):
			continue
		if not frappe.db.has_column(doctype, "module"):
			continue
		names = frappe.get_all(
			doctype,
			filters={"module": ["in", list(LEGACY_MODULES)]},
			pluck="name",
		)
		for name in names:
			frappe.db.set_value(doctype, name, "module", TARGET_MODULE, update_modified=False)

	# Explicit report fixes (even if module casing differs).
	for report_name in (
		"Container Tracking Detail",
		"Container Tracking Report",
		"Container Return Tracker",
	):
		if not frappe.db.exists("Report", report_name):
			continue
		current = frappe.db.get_value("Report", report_name, "module")
		if current != TARGET_MODULE:
			frappe.db.set_value(
				"Report",
				report_name,
				"module",
				TARGET_MODULE,
				update_modified=False,
			)

	frappe.db.commit()
	frappe.clear_cache()
