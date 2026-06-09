# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Website / portal routing for the CGM customer portal.

Customers are Website Users with the "Customer" role. We want them to
land on the branded `/portal` shipment dashboard after login - not the
desk (where they'd hit "Not Permitted") and not ERPNext's bare default
portal home.

`role_home_page` alone isn't enough: Frappe's auth flow sets the response
home page to `get_default_path() or get_home_page()`, and
`get_default_path()` resolves to `/app` whenever the site has desk apps
installed - bypassing the role hook. `route_customer_to_portal`
(registered as `on_session_creation`) runs after auth has set the
response, so the override wins.
"""

import frappe


def route_customer_to_portal(login_manager=None, **kwargs):
	"""Override post-login redirect so Customers land on `/portal`.

	Only applies to Website Users holding the Customer role, and never
	clobbers an explicit `redirect-to` deep link from the login form.

	Frappe invokes session-creation hooks with `login_manager=self`, so we
	accept it (and any future kwargs) even though we don't read it.
	"""
	try:
		user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
	except Exception:
		return

	if user_type != "Website User":
		return

	if "Customer" not in frappe.get_roles():
		return

	# Respect an explicit redirect-to from the login form (e.g. deep link
	# to a specific shipment).
	if frappe.local.response.get("redirect_to"):
		return

	frappe.local.response["home_page"] = "/portal"
