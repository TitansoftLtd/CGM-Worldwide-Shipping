"""Declaration roles need write on Task for permit receipts and certificates."""
from __future__ import annotations

import frappe

# Sites may use Declarant only, Declaration User only, or both.
DECLARATION_TASK_ROLES = ("Declaration User", "Declarant")


def execute():
	for role in DECLARATION_TASK_ROLES:
		_ensure_task_write(role)
	frappe.clear_cache(doctype="Task")


def _ensure_task_write(role: str) -> None:
	if not frappe.db.exists("Role", role):
		return

	name = frappe.db.get_value(
		"Custom DocPerm",
		{"parent": "Task", "role": role, "permlevel": 0},
		"name",
	)
	if name:
		frappe.db.set_value("Custom DocPerm", name, "write", 1, update_modified=False)
		return

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": "Task",
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role,
			"permlevel": 0,
			"read": 1,
			"write": 1,
			"create": 0,
			"delete": 0,
			"submit": 0,
			"cancel": 0,
			"amend": 0,
			"print": 0,
			"email": 0,
			"report": 0,
			"import": 0,
			"export": 1,
			"share": 0,
			"select": 1,
		}
	).insert(ignore_permissions=True)
