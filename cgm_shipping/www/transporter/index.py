# Copyright (c) 2026, Titansoft Limited and contributors

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal import (
	get_transporter_portal_dashboard,
	portal_context_base,
)

no_cache = 1


def get_context(context):
	try:
		transporter = portal_context_base(context)
		if not transporter:
			return
		context.title = _("My Allocations")
		context.update(get_transporter_portal_dashboard(transporter))
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="Transporter portal landing failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load allocations")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")
