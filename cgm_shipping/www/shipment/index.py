# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Customer portal: detail view of a single shipment (Project).

Reached from `/my-shipments` (each row links here). Visible at
`/shipment?name=<project>`. Shows the milestone stepper, shipment
metadata, per-container tracking timelines, and downloadable documents.

Ownership is re-verified server-side via `get_shipment_for_customer`;
the `name` URL parameter is untrusted, so a customer can only ever open
their own shipments.
"""

from urllib.parse import quote

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.inspection import (
	get_project_inspection_portal_context,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates import (
	get_my_updates_for_project,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
	container_timeline,
	customer_for_user,
	get_containers_for_shipment,
	get_shipment_documents,
	get_shipment_for_customer,
	get_shipment_permits,
	shipment_display_ref,
	shipment_progress,
	status_tone,
)

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	project = (frappe.form_dict.get("name") or "").strip()

	if frappe.session.user == "Guest":
		target = "/shipment"
		if project:
			target += "?name=" + quote(project, safe="")
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(target, safe="")
		raise frappe.Redirect

	try:
		_build_context(context, project)
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="Shipment detail portal failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load this shipment")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")


def _build_context(context, project):
	if not project:
		context.error_title = _("No shipment specified")
		context.error_message = _("Open this page from My Shipments.")
		return

	customer = customer_for_user(frappe.session.user)
	if not customer:
		context.error_title = _("No customer on your account")
		context.error_message = _(
			"Your portal account isn't connected to a Customer. Contact CGM Worldwide Shipping."
		)
		return

	shipment = get_shipment_for_customer(project, customer)
	if not shipment:
		# Don't distinguish "not found" from "not yours" - both render the
		# same guard so existence of other customers' shipments never leaks.
		context.error_title = _("Shipment not available")
		context.error_message = _(
			"This shipment doesn't exist or isn't consigned to your account."
		)
		return

	context.shipment = shipment
	context.ref = shipment.get("ref") or shipment_display_ref(shipment)
	context.progress = shipment_progress(shipment.custom_shipment_status)
	context.status_tone = status_tone(shipment.custom_shipment_status)

	# Prefer the newer "Description of Goods" field, falling back to the
	# legacy cargo description so older shipments still show something.
	context.cargo = shipment.get("custom_description_of_goods") or shipment.get(
		"custom_shipment_description"
	)

	# Pass-through charges billed on the shipment. Only surfaced when at
	# least one is non-zero, so clean shipments don't show an empty block.
	from frappe.utils import flt

	charge_fields = [
		(_("Breakbulk"), shipment.get("custom_breakbulk_charges")),
		(_("Handling"), shipment.get("custom_handling_charges")),
		(_("KEBS"), shipment.get("custom_kebs_charges")),
	]
	charges = [{"label": label, "amount": flt(amt)} for label, amt in charge_fields if flt(amt)]
	context.charges = charges
	context.charges_total = sum(c["amount"] for c in charges)
	context.charges_currency = frappe.defaults.get_global_default("currency")

	containers = get_containers_for_shipment(project)
	for c in containers:
		c["timeline"] = container_timeline(c)
		c["has_charges"] = bool(
			(c.get("demurrage_days") or 0)
		)
	context.containers = containers

	context.documents = get_shipment_documents(project)
	context.permits = get_shipment_permits(project)
	context.inspection = get_project_inspection_portal_context(project, customer)

	# Only updates posted by the logged-in customer user.
	context.updates = get_my_updates_for_project(project, limit=100)
	context.updates_json = frappe.as_json(context.updates)
