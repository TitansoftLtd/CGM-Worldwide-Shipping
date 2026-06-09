# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Customer portal: list of the logged-in customer's quotations.

Visible at `/my-quotations`. Lists Sales Quotations raised to the
customer with status, value and validity, each with a guarded PDF
download. Mirrors the `/my-shipments` page structure.
"""

from urllib.parse import quote

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
	customer_display_name,
	customer_for_user,
	get_customer_quotations,
)

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote("/my-quotations", safe="")
		raise frappe.Redirect

	try:
		_build_context(context)
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="My Quotations portal failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load your quotations")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")


def _build_context(context):
	customer = customer_for_user(frappe.session.user)
	context.customer = customer
	context.customer_name = customer_display_name(customer)

	if not customer:
		context.quotations = []
		context.no_customer = True
		return

	context.quotations = get_customer_quotations(customer)
