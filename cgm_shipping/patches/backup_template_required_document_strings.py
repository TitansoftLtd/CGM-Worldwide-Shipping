# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe


def execute() -> None:
	"""Before fieldtype change: stash legacy comma-separated values on each template row."""
	if not frappe.db.table_exists("CGM Task Template Item"):
		return
	if not frappe.db.has_column("CGM Task Template Item", "required_document_types"):
		return
	coltype = (frappe.db.get_column_type("CGM Task Template Item", "required_document_types") or "").lower()
	if coltype not in ("varchar", "text", "longtext"):
		return

	rows = frappe.db.sql(
		"""
		select name, required_document_types
		from `tabCGM Task Template Item`
		where ifnull(required_document_types, '') != ''
		""",
		as_dict=True,
	)
	frappe.cache.set_value(
		"cgm_template_required_docs_migration",
		{r.name: r.required_document_types for r in rows},
	)
