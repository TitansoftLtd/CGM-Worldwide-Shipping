"""Stop deploys from overwriting the permissions a site has set for itself.

Every migrate re-imports each DocType from the app and **replaces its `DocPerm`
rows** with whatever the JSON says. Anything set by editing a DocType's
Permissions tab in production was therefore deleted on every deploy, silently and
repeatedly. That is the "it wipes after every deployment" complaint.

Frappe already has the escape hatch: once a DocType has any `Custom DocPerm` row,
`Meta.set_custom_permissions` uses those instead, and a DocType re-import cannot
touch them. This moves every DocType the app owns behind that hatch on the first
deploy and keeps it there.

The rule, per role:

* **A role already present is left completely alone.** Whatever the site has done
  to it - widened it, narrowed it, removed a flag - is a decision, and a deploy is
  not the place to reverse it.
* **A role the app ships but the site has never seen is added**, with the flags
  from the JSON. That is how a permission written locally and committed still
  reaches production.

So the app can introduce access, and never takes it away. Removing a role remains
a deliberate act someone performs on the site, not something a deploy does on
their behalf.

Only DocTypes belonging to this app are touched. ERPNext's and Frappe's own are
left entirely alone: their permissions are not ours to freeze.
"""

from __future__ import annotations

import frappe

MODULE = "CGM Worldwide Shipping"

#: Flags copied when a role is added. `permlevel` and `if_owner` identify the row
#: rather than describing it, so they are handled separately.
PERM_FLAGS = (
	"read", "write", "create", "delete", "submit", "cancel", "amend",
	"report", "export", "import", "share", "print", "email", "select",
	"set_user_permissions",
)


def _app_doctypes() -> list[str]:
	"""DocTypes this app owns. Child tables inherit their parent's permissions."""
	return frappe.get_all(
		"DocType",
		filters={"module": MODULE, "custom": 0, "istable": 0},
		pluck="name",
		order_by="name",
	)


def ensure_permissions_survive_deploy() -> None:
	from frappe.permissions import setup_custom_perms

	frozen, added = [], []

	for doctype in _app_doctypes():
		# First deploy for this DocType: copy what is live into Custom DocPerm, so
		# the next re-import of the JSON cannot reach it.
		if setup_custom_perms(doctype):
			frozen.append(doctype)

		shipped = frappe.get_all(
			"DocPerm",
			filters={"parent": doctype},
			fields=["*"],
		)
		if not shipped:
			continue

		existing = {
			(row.role, row.permlevel or 0, row.if_owner or 0)
			for row in frappe.get_all(
				"Custom DocPerm",
				filters={"parent": doctype},
				fields=["role", "permlevel", "if_owner"],
			)
		}

		for row in shipped:
			key = (row.role, row.permlevel or 0, row.if_owner or 0)
			if key in existing:
				# The site already has an opinion about this role. Keep out of it.
				continue
			custom = frappe.new_doc("Custom DocPerm")
			custom.parent = doctype
			custom.parenttype = "DocType"
			custom.parentfield = "permissions"
			custom.role = row.role
			custom.permlevel = row.permlevel or 0
			custom.if_owner = row.if_owner or 0
			for flag in PERM_FLAGS:
				custom.set(flag, row.get(flag) or 0)
			custom.insert(ignore_permissions=True)
			existing.add(key)
			added.append(f"{doctype}: {row.role}")

	if frozen or added:
		frappe.db.commit()
		frappe.clear_cache()

	if frozen:
		print(f"Permissions now protected from deploys on {len(frozen)} doctype(s).")
	if added:
		print("Permissions added from the app:")
		for item in added:
			print(f"  {item}")
