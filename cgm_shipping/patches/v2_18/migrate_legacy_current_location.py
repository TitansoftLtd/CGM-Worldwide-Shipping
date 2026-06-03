"""Map legacy Project current location labels to valid Select options."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("Custom Field", "Project-custom_current_location"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabProject`
		SET custom_current_location = %s
		WHERE custom_current_location = %s
		""",
		("At origin", "Origin Country"),
	)

	frappe.db.commit()
	frappe.clear_cache(doctype="Project")

