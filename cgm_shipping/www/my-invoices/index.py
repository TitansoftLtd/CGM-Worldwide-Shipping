# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Customer portal: list of the logged-in customer's sales invoices.

Visible at `/my-invoices`. Lists submitted Sales Invoices with status,
total, outstanding balance and due date, plus a guarded PDF download and
a headline total-outstanding figure. Mirrors the `/my-shipments` page.
"""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import flt

from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
	customer_display_name,
	customer_for_user,
	get_customer_invoices,
)

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote("/my-invoices", safe="")
		raise frappe.Redirect

	try:
		_build_context(context)
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="My Invoices portal failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load your invoices")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")


def _build_context(context):
	customer = customer_for_user(frappe.session.user)
	context.customer = customer
	context.customer_name = customer_display_name(customer)

	if not customer:
		context.invoices = []
		context.no_customer = True
		return

	invoices = get_customer_invoices(customer)
	context.invoices = invoices
	context.total_outstanding = sum(flt(i.outstanding_amount) for i in invoices)
	# Currency for the headline figure - use the first invoice's, falling
	# back to the company default. Mixed-currency portfolios are rare here.
	context.currency = invoices[0].currency if invoices else frappe.defaults.get_global_default("currency")
