# Copyright (c) 2026, Titansoft Limited and contributors
"""Transporter portal: every conversation this haulier has with CGM.

Visible at `/transporter/messages`, the counterpart to the customer's
`/my-messages`. General queries - anything not about a particular job - live
here with their own threads; conversations tied to an allocation are listed
with a link into that allocation's Messages tab.
"""

from urllib.parse import quote

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal import (
	portal_context_base,
	transporter_allocation_overview,
	transporter_general_summaries,
	transporter_general_thread,
)

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(
			"/transporter/messages", safe=""
		)
		raise frappe.Redirect

	try:
		transporter = portal_context_base(context)
		if not transporter:
			return
		context.title = _("Messages")
		_build_context(context, transporter)
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="Transporter messages failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load your messages")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")


def _build_context(context, transporter):
	queries = transporter_general_summaries(transporter)
	jobs = transporter_allocation_overview(transporter)
	context.queries = queries
	context.jobs = jobs
	context.unread_total = sum(q["unread_count"] for q in queries) + sum(
		j["unread_count"] for j in jobs
	)

	requested = (frappe.form_dict.get("query") or "").strip()
	thread = transporter_general_thread(transporter, requested) if requested else []
	context.open_query = requested if thread else ""
	context.open_query_subject = thread[0]["subject"] if thread else ""
	context.thread_json = frappe.as_json(thread)
