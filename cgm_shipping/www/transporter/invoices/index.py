# Copyright (c) 2026, Titansoft Limited and contributors
"""Transporter portal: purchase invoices CGM has shared.

Visible at `/transporter/invoices`. Outstanding amounts are what CGM still
owes the transporter. Paid invoices appear after CGM records payment.
"""

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share import (
	get_transporter_invoice_summary,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal import (
	portal_context_base,
)

no_cache = 1


def get_context(context):
	try:
		transporter = portal_context_base(context)
		if not transporter:
			return
		context.title = _("Invoices from CGM")
		context.update(get_transporter_invoice_summary(transporter))
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="Transporter invoices page failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load invoices")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")
