import frappe

REFERENCE_MASTERS = [
	"Cargo Type",
	"CFS Location",
	"CGM Task Template",
	"Charge Item",
	"Clearance Port",
	"Clearance Station",
	"Container Tracker Mode",
	"Customs Tax Type",
	"Document Type",
	"Mode of Transport",
	# Package Type ships four roles, so it never looked thin - but production's
	# Custom DocPerm set replaced those with a different five, none of them "All".
	# Anyone outside that five still could not pick a package type.
	"Package Type",
	"Permit Type",
	"Shipment Type",
	"Warehouse Station",
]

GRANT = {
	"read": 1, "select": 1, "report": 1, "print": 1, "email": 1,
	"write": 0, "create": 0, "delete": 0, "share": 0, "export": 0,
}


def execute():
	"""Grant through Frappe's own API rather than writing permission rows.

	`add_permission` calls `setup_custom_perms` first, which copies the existing
	shipped rows into Custom DocPerm before adding anything. That matters: a
	Custom DocPerm set replaces the shipped set wholesale, so inserting a lone row
	onto a DocType that had none would have taken System Manager's write and
	create away with it.
	"""
	from frappe.permissions import add_permission, update_permission_property

	granted, already, missing = [], [], []

	for doctype in REFERENCE_MASTERS:
		if not frappe.db.exists("DocType", doctype):
			missing.append(doctype)
			continue

		existing = frappe.db.get_value(
			"Custom DocPerm", {"parent": doctype, "role": "All", "permlevel": 0, "if_owner": 0}
		)
		if existing and frappe.db.get_value("Custom DocPerm", existing, "read"):
			already.append(doctype)
			continue

		if not existing:
			add_permission(doctype, "All", 0)
		for ptype, value in GRANT.items():
			update_permission_property(doctype, "All", 0, ptype, value)
		frappe.clear_cache(doctype=doctype)
		granted.append(doctype)

	frappe.db.commit()

	if granted:
		print(f"Readable by All now: {', '.join(granted)}")
	if already:
		print(f"Already readable: {', '.join(already)}")
	if missing:
		print(f"Not on this site: {', '.join(missing)}")
