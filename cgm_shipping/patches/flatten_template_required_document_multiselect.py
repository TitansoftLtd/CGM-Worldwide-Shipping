# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
	serialize_required_document_types,
)


def execute() -> None:
	"""Copy Table MultiSelect child rows back onto the Data field before reload."""
	child_doctype = "CGM Task Template Document Type"
	if not frappe.db.table_exists(f"tab{child_doctype}"):
		return

	rows = frappe.db.sql(
		f"""
		select parent, document_type
		from `tab{child_doctype}`
		where ifnull(document_type, '') != ''
		order by parent, idx
		""",
		as_dict=True,
	)
	if not rows:
		return

	by_parent: dict[str, list[str]] = {}
	for row in rows:
		by_parent.setdefault(row.parent, []).append(row.document_type)

	for parent, names in by_parent.items():
		if not frappe.db.exists("CGM Task Template Item", parent):
			continue
		frappe.db.set_value(
			"CGM Task Template Item",
			parent,
			"required_document_types",
			serialize_required_document_types(names),
			update_modified=False,
		)

	frappe.clear_cache(doctype="CGM Task Template Item")
