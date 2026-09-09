# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Customer portal: detail view of a single container (Container Tracker).

Reached from the container list on `/shipment`. Visible at
`/container?name=<container tracker>`. Shows the movement timeline, the
free-days / demurrage position, and the two-way conversation with
operations for that box. Feedback is left on the shipment, not the box - see
`/shipment` - so this page carries no rating form.

Ownership is re-verified server-side through `get_container_for_customer`;
the `name` URL parameter is untrusted, so a customer can only ever open a
container that sits on one of their own shipments.
"""

from urllib.parse import quote

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
	container_timeline,
	customer_for_user,
	get_container_for_customer,
	get_customer_conversation,
	get_shipment_for_customer,
	shipment_display_ref,
)

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	tracker = (frappe.form_dict.get("name") or "").strip()

	if frappe.session.user == "Guest":
		target = "/container"
		if tracker:
			target += "?name=" + quote(tracker, safe="")
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(target, safe="")
		raise frappe.Redirect

	try:
		_build_context(context, tracker)
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="Container detail portal failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load this container")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")


def _build_context(context, tracker):
	if not tracker:
		context.error_title = _("No container specified")
		context.error_message = _("Open this page from your shipment.")
		return

	customer = customer_for_user(frappe.session.user)
	if not customer:
		context.error_title = _("No customer on your account")
		context.error_message = _(
			"Your portal account isn't connected to a Customer. Contact CGM Worldwide Shipping."
		)
		return

	container = get_container_for_customer(tracker, customer)
	if not container:
		# Same guard for "not found" and "not yours" - never leak existence.
		context.error_title = _("Container not available")
		context.error_message = _(
			"This container doesn't exist or isn't on one of your shipments."
		)
		return

	context.container = container
	context.container_label = container.get("container_number") or _("Container")
	context.timeline = container_timeline(container)

	shipment = get_shipment_for_customer(container.project, customer)
	context.shipment = shipment
	context.shipment_ref = shipment_display_ref(shipment) if shipment else container.project
	context.shipment_url = "/shipment?name=" + quote(container.project, safe="")

	context.conversation = get_customer_conversation(
		container.project, container_tracker=tracker
	)
	context.conversation_json = frappe.as_json(context.conversation)
	context.unread_count = sum(1 for m in context.conversation if m.get("unread"))
