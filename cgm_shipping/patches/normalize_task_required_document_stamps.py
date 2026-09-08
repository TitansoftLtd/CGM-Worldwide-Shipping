# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
	normalize_required_document_type_stamp,
)


def execute() -> None:
	"""Rewrite Task stamps (Entry Slip → Entry, etc.) to canonical Document Type names."""
	if not frappe.get_meta("Task").has_field("custom_required_document_types"):
		return

	tasks = frappe.get_all(
		"Task",
		filters={"custom_required_document_types": ["!=", ""]},
		fields=["name", "custom_required_document_types"],
	)
	updated = 0
	for row in tasks:
		raw = (row.custom_required_document_types or "").strip()
		normalized = normalize_required_document_type_stamp(raw)
		if normalized and normalized != raw:
			frappe.db.set_value(
				"Task",
				row.name,
				"custom_required_document_types",
				normalized,
				update_modified=False,
			)
			updated += 1
	if updated:
		frappe.clear_cache(doctype="Task")
