"""Ensure Cargo Size / Package Type have Select so BL container Link pickers work.

Without Select, users see an empty/blocked picker when choosing Cargo Size on
Bill of Lading → Container Information. Non–System Manager roles get Read+Select
only (no create/write).
"""

from __future__ import annotations

import frappe

# role → permission flags (explicit zeros keep masters from becoming editable)
_ROLE_PERMS: dict[str, dict[str, int]] = {
	"System Manager": {
		"read": 1,
		"select": 1,
		"write": 1,
		"create": 1,
		"delete": 1,
		"export": 1,
		"print": 1,
		"report": 1,
		"email": 1,
		"share": 1,
	},
	"CGM Documentation": {
		"read": 1,
		"select": 1,
		"write": 0,
		"create": 0,
		"delete": 0,
		"export": 1,
		"print": 1,
		"report": 1,
		"email": 0,
		"share": 0,
	},
	"Operations Manager": {
		"read": 1,
		"select": 1,
		"write": 0,
		"create": 0,
		"delete": 0,
		"export": 1,
		"print": 1,
		"report": 1,
		"email": 0,
		"share": 0,
	},
	"Declarant": {
		"read": 1,
		"select": 1,
		"write": 0,
		"create": 0,
		"delete": 0,
		"export": 0,
		"print": 0,
		"report": 0,
		"email": 0,
		"share": 0,
	},
	"All": {
		"read": 1,
		"select": 1,
		"write": 0,
		"create": 0,
		"delete": 0,
		"export": 0,
		"print": 0,
		"report": 0,
		"email": 0,
		"share": 0,
	},
}


def execute() -> None:
	changed = False
	for doctype in ("Cargo Size", "Package Type"):
		if not frappe.db.exists("DocType", doctype):
			continue
		if _ensure_select_perms(doctype):
			changed = True
	if changed:
		frappe.clear_cache()
		frappe.db.commit()


def _ensure_select_perms(doctype: str) -> bool:
	doc = frappe.get_doc("DocType", doctype)
	existing = {row.role: row for row in (doc.permissions or []) if row.role}
	changed = False

	roles = list(_ROLE_PERMS.keys())
	if doctype == "Package Type" and "Declarant" in roles:
		roles.remove("Declarant")

	for role in roles:
		flags = _ROLE_PERMS[role]
		if role != "All" and not frappe.db.exists("Role", role):
			continue

		row = existing.get(role)
		if not row:
			doc.append("permissions", {"role": role, **flags})
			changed = True
			continue

		for key, value in flags.items():
			if int(row.get(key) or 0) != int(value):
				row.set(key, value)
				changed = True

	if changed:
		# Avoid rewriting app JSON during migrate; only update DB DocPerm.
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)
	return changed
