"""Role groups for notifications and finance/declaration checks.

The source of truth is CGM Shipping Settings → Roles. Initial values are seeded
on install / migrate (see cgm_setup.py); there is no code fallback, so an empty
table means "no roles in that group". Depends only on frappe (no import cycle).
"""

from __future__ import annotations

import frappe

# group key -> CGM Shipping Settings fieldname
_GROUPS = {
	"finance": "custom_finance_roles",
	"operations": "custom_operations_roles",
	"declaration": "custom_declaration_roles",
}


def _roles(group: str) -> tuple[str, ...]:
	fieldname = _GROUPS[group]
	try:
		settings = frappe.get_cached_doc("CGM Shipping Settings")
	except Exception:
		# Settings single may not exist yet (very early in install) — treat as empty.
		return ()
	return tuple(
		(row.role or "").strip()
		for row in (settings.get(fieldname) or [])
		if row.get("role")
	)


def finance_roles() -> tuple[str, ...]:
	return _roles("finance")


def operations_roles() -> tuple[str, ...]:
	return _roles("operations")


def declaration_roles() -> tuple[str, ...]:
	return _roles("declaration")
