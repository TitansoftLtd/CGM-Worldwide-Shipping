# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
	coerce_legacy_document_type_tokens,
	parse_required_document_types,
	set_template_row_required_document_types,
)


def execute() -> None:
	"""After Table MultiSelect migrate: import only exact Document Type master names."""
	frappe.reload_doc(
		"cgm_worldwide_shipping",
		"doctype",
		"cgm_task_template_document_type",
		force=True,
	)
	frappe.reload_doc(
		"cgm_worldwide_shipping",
		"doctype",
		"cgm_task_template_item",
		force=True,
	)

	backup = frappe.cache.get_value("cgm_template_required_docs_migration") or {}
	if not backup:
		return

	for row_name, raw in backup.items():
		if not frappe.db.exists("CGM Task Template Item", row_name):
			continue
		names = coerce_legacy_document_type_tokens(parse_required_document_types(raw))
		if not names:
			continue
		row = frappe.get_doc("CGM Task Template Item", row_name)
		if row.get("required_document_types"):
			continue
		parent_name = row.parent
		if not parent_name:
			continue
		template = frappe.get_doc("CGM Task Template", parent_name)
		for template_row in template.get("tasks") or []:
			if template_row.name != row_name:
				continue
			set_template_row_required_document_types(template_row, names)
			break
		template.flags.ignore_permissions = True
		template.save(ignore_permissions=True)

	frappe.cache.delete_value("cgm_template_required_docs_migration")
	frappe.clear_cache(doctype="CGM Task Template Item")
