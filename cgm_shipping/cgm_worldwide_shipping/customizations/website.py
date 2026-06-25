# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Website / portal routing for CGM customer and transporter portals.

Transporter portal access is driven by the Supplier **Portal Users** table
(`get_transporter_for_user`) — not by User Type alone. Anyone listed on a
transporter Supplier's portal users is sent to `/transporter` after login and
away from `/desk`, unless they hold an internal override role.

Customers remain **Website User** accounts landing on `/portal`.
"""

import frappe

# Internal staff who may stay on Desk even when also linked on a transporter Supplier.
_DESK_OVERRIDE_ROLES = frozenset({"Administrator", "System Manager"})


def _user_may_use_desk_instead(user: str) -> bool:
	return bool(set(frappe.get_roles(user)) & _DESK_OVERRIDE_ROLES)


def _transporter_portal_path(user: str) -> str | None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal import (
		get_transporter_for_user,
	)

	if get_transporter_for_user(user):
		return "/transporter"
	return None


def _customer_portal_path(user: str) -> str | None:
	if frappe.db.get_value("User", user, "user_type") != "Website User":
		return None
	if "Customer" in frappe.get_roles(user):
		return "/portal"
	return None


def get_cgm_website_user_home_page(user: str) -> str | None:
	"""Frappe hook: home page slug for website users (no leading slash)."""
	if not user or user == "Guest":
		return None

	transporter = _transporter_portal_path(user)
	if transporter:
		return transporter.strip("/")

	if frappe.db.get_value("User", user, "user_type") != "Website User":
		return None

	customer = _customer_portal_path(user)
	return customer.strip("/") if customer else None


def route_cgm_portal_after_login(login_manager=None, **kwargs):
	"""Override post-login redirect for CGM portal users.

	Transporter portal users are redirected regardless of User Type (System or
	Website) as long as they are on a transporter Supplier's Portal Users list.
	"""
	if frappe.session.user == "Guest":
		return

	if frappe.local.response.get("redirect_to"):
		return

	if _user_may_use_desk_instead(frappe.session.user):
		return

	transporter_home = _transporter_portal_path(frappe.session.user)
	if transporter_home:
		frappe.local.response["home_page"] = transporter_home
		return

	try:
		user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
	except Exception:
		return

	if user_type != "Website User":
		return

	customer_home = _customer_portal_path(frappe.session.user)
	if customer_home:
		frappe.local.response["home_page"] = customer_home


def redirect_transporter_portal_users_from_desk():
	"""Send transporter portal users to `/transporter` when they hit Desk/App."""
	if frappe.session.user == "Guest":
		return

	if _user_may_use_desk_instead(frappe.session.user):
		return

	request = getattr(frappe.local, "request", None)
	if not request:
		return

	path = (request.path or "").lower()
	if not (path.startswith("/desk") or path.startswith("/app")):
		return

	if _transporter_portal_path(frappe.session.user):
		frappe.local.flags.redirect_location = "/transporter"
		raise frappe.Redirect


def route_customer_to_portal(login_manager=None, **kwargs):
	"""Backward-compatible alias."""
	route_cgm_portal_after_login(login_manager=login_manager, **kwargs)


def route_transporter_to_portal(login_manager=None, **kwargs):
	"""Backward-compatible alias."""
	route_cgm_portal_after_login(login_manager=login_manager, **kwargs)
