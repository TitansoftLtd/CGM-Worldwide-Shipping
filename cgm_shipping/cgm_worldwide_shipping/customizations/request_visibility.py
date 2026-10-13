"""Who sees every Material Request, and who sees only their own.

HRMS gives each employee a user permission on their own Employee record. A
Material Request names its requester in an Employee field, so that permission
silently filtered the list to requests a user had raised - which is right for
most staff and wrong for the people who fund and approve them. A Funding
Approver saw 5 of 17 requests and could not find the operational expenses
waiting on her.

Frappe has no way to let particular roles past a user permission; it is all or
nothing per field. So the requester field no longer applies user permissions,
and the same rule is applied here instead, with one difference: the roles listed
under CGM Shipping Settings > Roles > "See all Material Requests" are let
through.

For everyone else nothing changes. They see what they saw before - requests
naming them as requester, and requests with no requester - plus any they
created. Only this one field is involved: Company, Project and every other user
permission still applies to Material Requests exactly as Frappe applies it.
"""

from __future__ import annotations

import frappe

SETTINGS_FIELD = "material_request_all_roles"

# Used while the settings table is empty, so the rule works on a fresh install
# and an emptied table means these, never "nobody".
DEFAULT_ROLES = (
	"Finance User",
	"Finance Manager",
	"Funding Approver",
	"Accounts Manager",
	"Accounts User",
	"Operations Manager",
	"Director",
)

# Always let through, whatever the table says.
ALWAYS = ("System Manager",)


def see_all_roles() -> set[str]:
	roles: list[str] = []
	try:
		settings = frappe.get_cached_doc("CGM Shipping Settings")
		if settings.meta.has_field(SETTINGS_FIELD):
			roles = [row.role for row in settings.get(SETTINGS_FIELD) or [] if row.role]
	except Exception:
		roles = []
	return set(roles or DEFAULT_ROLES) | set(ALWAYS)


def user_sees_all(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(frappe.get_roles(user)) & see_all_roles())


def restricted_employees(user: str | None = None) -> list[str]:
	"""The Employee records this user is limited to, as their user permissions say.

	Empty when the user has no Employee user permission at all - such a user was
	never restricted, and is not restricted now.
	"""
	user = user or frappe.session.user
	permissions = frappe.permissions.get_user_permissions(user) or {}
	return [row.get("doc") for row in permissions.get("Employee") or [] if row.get("doc")]


def material_request_query_conditions(user: str | None = None) -> str:
	"""`permission_query_conditions` hook: the list, reports and link searches."""
	user = user or frappe.session.user
	if user_sees_all(user):
		return ""
	employees = restricted_employees(user)
	if not employees:
		return ""
	names = ", ".join(frappe.db.escape(name) for name in employees)
	return (
		"(ifnull(`tabMaterial Request`.`custom_employee`, '') = ''"
		f" or `tabMaterial Request`.`custom_employee` in ({names})"
		f" or `tabMaterial Request`.`owner` = {frappe.db.escape(user)})"
	)


def material_request_has_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	"""`has_permission` hook: opening one request. Can only deny, never grant."""
	user = user or frappe.session.user
	if user_sees_all(user):
		return True
	employees = restricted_employees(user)
	if not employees:
		return True
	requester = doc.get("custom_employee")
	return not requester or requester in employees or doc.get("owner") == user


def ensure_see_all_roles() -> None:
	"""Seed the default roles into Settings when the table is empty. Runs on migrate."""
	settings = frappe.get_single("CGM Shipping Settings")
	if not settings.meta.has_field(SETTINGS_FIELD) or settings.get(SETTINGS_FIELD):
		return
	for role in DEFAULT_ROLES:
		if frappe.db.exists("Role", role):
			settings.append(SETTINGS_FIELD, {"role": role})
	settings.flags.ignore_permissions = True
	settings.flags.ignore_mandatory = True
	settings.save()
