"""Remove nested child table from CGM Task Template Item so row Edit works.

Frappe does not support Table-inside-Table; the pencil Edit control fails with a JS error.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	frappe.reload_doc(
		"cgm_worldwide_shipping",
		"doctype",
		"cgm_task_template_item",
		force=True,
	)
	# Ensure obsolete nested Table field is gone from DB meta.
	frappe.db.delete(
		"DocField",
		{"parent": "CGM Task Template Item", "fieldname": "required_documents"},
	)
	frappe.clear_cache(doctype="CGM Task Template Item")
	frappe.clear_cache(doctype="CGM Task Template")
