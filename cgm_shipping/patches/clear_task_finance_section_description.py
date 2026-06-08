"""Remove helper text under Invoices & Receipts section on Task."""

import frappe


def execute():
	for name in frappe.get_all(
		"Custom Field",
		filters={"fieldname": "custom_section_task_finance", "dt": "Task"},
		pluck="name",
	):
		frappe.db.set_value("Custom Field", name, "description", "", update_modified=False)
	frappe.clear_cache(doctype="Task")
