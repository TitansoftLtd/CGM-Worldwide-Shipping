# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Customer portal: list of the logged-in customer's shipments.

Visible at `/my-shipments`. Lists every non-Draft Project for the
customer with status, mode, B/L number and ETA/ATA, each linking to the
`/shipment` detail view. An optional `?status=` query param filters the
list to one shipment status (linked from the dashboard KPI cards).
"""

from urllib.parse import quote

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
	customer_display_name,
	customer_for_user,
	get_customer_shipments,
	status_tone,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
	display_ref_from_values,
)

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote("/my-shipments", safe="")
		raise frappe.Redirect

	try:
		_build_context(context)
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="My Shipments portal failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load your shipments")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")


def _build_context(context):
	customer = customer_for_user(frappe.session.user)
	context.customer = customer
	context.customer_name = customer_display_name(customer)

	if not customer:
		context.shipments = []
		context.no_customer = True
		return

	status_filter = (frappe.form_dict.get("status") or "").strip()
	context.status_filter = status_filter

	shipments = get_customer_shipments(customer)
	if status_filter:
		shipments = [s for s in shipments if s.custom_shipment_status == status_filter]

	for s in shipments:
		s["tone"] = status_tone(s.custom_shipment_status)
		s["url"] = "/shipment?name=" + quote(s.name, safe="")
		s["ref"] = display_ref_from_values(s)

	context.shipments = shipments
