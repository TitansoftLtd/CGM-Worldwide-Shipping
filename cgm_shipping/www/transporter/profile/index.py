# Copyright (c) 2026, Titansoft Limited and contributors

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal import (
	get_transporter_profile,
	portal_context_base,
)

no_cache = 1


def get_context(context):
	try:
		transporter = portal_context_base(context)
		if not transporter:
			return
		context.title = _("Company Profile")
		context.profile = get_transporter_profile()
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="Transporter profile page failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load profile")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")
