import frappe


def execute():
	ensure_creator_roles_can_edit_project()


def ensure_creator_roles_can_edit_project():
	# Step 1: normalize custom permissions where create access exists.
	custom_perms = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": "Project", "permlevel": 0, "create": 1},
		fields=["name"],
	)
	for row in custom_perms:
		perm = frappe.get_doc("Custom DocPerm", row.name)
		perm.read = 1
		perm.write = 1
		perm.save(ignore_permissions=True)

	# Step 2: normalize standard permissions where create access exists.
	doc_perms = frappe.get_all(
		"DocPerm",
		filters={"parent": "Project", "permlevel": 0, "create": 1},
		fields=["name"],
	)
	for row in doc_perms:
		perm = frappe.get_doc("DocPerm", row.name)
		perm.read = 1
		perm.write = 1
		perm.save(ignore_permissions=True)

