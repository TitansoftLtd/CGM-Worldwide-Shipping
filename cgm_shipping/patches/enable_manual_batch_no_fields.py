"""Allow manual Batch No entry on Opportunity and Project intake forms."""

from __future__ import annotations

import frappe


def execute():
	for dt in ("Opportunity", "Project"):
		name = f"{dt}-custom_batch_no"
		if not frappe.db.exists("Custom Field", name):
			continue
		frappe.db.set_value("Custom Field", name, "read_only", 0, update_modified=False)

	frappe.clear_cache(doctype="Opportunity")
	frappe.clear_cache(doctype="Project")
