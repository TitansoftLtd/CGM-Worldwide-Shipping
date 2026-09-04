# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Customer portal: sales invoices + Finance-shared clearance fee invoices.

Visible at `/my-invoices`. Clients can download shared fee invoices, confirm
"I have paid", then optionally attach a payment receipt for the Client will pay path.
"""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import flt

from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
	apply_customer_portal_layout,
	customer_display_name,
	customer_for_user,
	get_customer_invoices,
	get_customer_shared_fee_invoices,
	outstanding_totals_by_currency,
)

no_cache = 1


def get_context(context):
	apply_customer_portal_layout(context)

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
		context.fee_invoices = []
		context.no_customer = True
		return

	invoices = get_customer_invoices(customer)
	fee_invoices = get_customer_shared_fee_invoices(customer)
	context.invoices = invoices
	context.fee_invoices = fee_invoices
	context.pending_fees = [f for f in fee_invoices if not f.get("has_payment_proof")]
	outstanding_totals = outstanding_totals_by_currency(invoices)
	context.outstanding_totals = outstanding_totals
	context.has_outstanding = bool(outstanding_totals)
	context.total_outstanding = sum(flt(t["amount"]) for t in outstanding_totals)
	context.currency = (
		outstanding_totals[0]["currency"]
		if outstanding_totals
		else (invoices[0].currency if invoices else frappe.defaults.get_global_default("currency"))
	)
