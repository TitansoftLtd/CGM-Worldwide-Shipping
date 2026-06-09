# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Customer portal: every downloadable document across the customer's shipments.

Visible at `/documents`. Aggregates the vetted Shipment Document rows from
all of the customer's Projects into one list, each with a guarded download
link and a link back to its shipment. Downloads stream through the
ownership-checked `download_shipment_document` endpoint.
"""

from urllib.parse import quote

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
	customer_display_name,
	customer_for_user,
	get_all_customer_documents,
)

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote("/documents", safe="")
		raise frappe.Redirect

	try:
		_build_context(context)
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="Documents portal failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load your documents")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")


def _build_context(context):
	customer = customer_for_user(frappe.session.user)
	context.customer = customer
	context.customer_name = customer_display_name(customer)

	if not customer:
		context.documents = []
		context.no_customer = True
		return

	context.documents = get_all_customer_documents(customer)
