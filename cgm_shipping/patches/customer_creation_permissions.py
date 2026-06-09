import frappe


def execute():
	ensure_customer_permission("CGM Documentation")
	ensure_customer_permission("Operations Manager")


def ensure_customer_permission(role_name):
	if not frappe.db.exists("Role", role_name):
		return

	perm_name = frappe.db.get_value(
		"Custom DocPerm",
		{"parent": "Customer", "role": role_name, "permlevel": 0},
		"name",
	)
	if perm_name:
		perm = frappe.get_doc("Custom DocPerm", perm_name)
	else:
		perm = frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Customer",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role_name,
				"permlevel": 0,
			}
		)

	perm.read = 1
	perm.write = 1
	perm.create = 1
	perm.delete = 0
	perm.submit = 0
	perm.cancel = 0
	perm.amend = 0
	perm.save(ignore_permissions=True)

