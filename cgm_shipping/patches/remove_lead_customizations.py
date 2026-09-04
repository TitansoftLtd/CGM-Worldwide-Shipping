"""Strip CGM customizations from Lead so it uses stock ERPNext.

Deletes Custom Fields, Property Setters, extra Custom DocPerms, and Client
Scripts. Idempotent: no-op when Lead is already uncustomized.

Source custom/lead.json was removed; this patch clears records already on
upgrade sites. Fresh installs never receive the Lead customizations.
"""

from __future__ import annotations

import frappe

DT = "Lead"


def execute() -> None:
	_delete_docs("Custom Field", {"dt": DT})
	_delete_docs("Property Setter", {"doc_type": DT})
	_delete_docs("Client Script", {"dt": DT})
	if frappe.db.table_exists("Custom DocPerm"):
		frappe.db.delete("Custom DocPerm", {"parent": DT})
	frappe.clear_cache(doctype=DT)


def _delete_docs(doctype: str, filters: dict) -> None:
	if not frappe.db.table_exists(doctype):
		return
	for name in frappe.get_all(doctype, filters=filters, pluck="name"):
		frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)
