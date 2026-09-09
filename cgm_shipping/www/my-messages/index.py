# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Customer portal: every conversation this customer has with operations.

Visible at `/my-messages`, and where the "New Messages" tile on the portal
landing points. One row per shipment - newest message, who sent it, and how
many CGM messages are still unread - each opening that shipment's Messages
tab, plus general queries for anything not tied to a shipment - each its own
conversation, opened with `?query=<first message>`.
"""

from urllib.parse import quote

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
	customer_conversation_summaries,
	customer_display_name,
	customer_for_user,
	general_query_summaries,
	general_query_thread,
)

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(
			"/my-messages", safe=""
		)
		raise frappe.Redirect

	try:
		_build_context(context)
	except frappe.Redirect:
		raise
	except Exception:
		frappe.log_error(title="My Messages portal failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load your messages")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")


def _build_context(context):
	customer = customer_for_user(frappe.session.user)
	context.customer = customer
	context.customer_name = customer_display_name(customer)

	if not customer:
		context.conversations = []
		context.no_customer = True
		return

	conversations = customer_conversation_summaries(customer)
	context.conversations = conversations

	# General queries are not about any one shipment, so they live here. Each
	# is its own conversation - `?query=` opens one, otherwise they are listed.
	queries = general_query_summaries(customer)
	context.queries = queries
	context.general_unread = sum(q["unread_count"] for q in queries)

	requested = (frappe.form_dict.get("query") or "").strip()
	thread = general_query_thread(customer, requested) if requested else []
	if requested and not thread:
		context.error_title = _("Query not found")
		context.error_message = _("This query doesn't exist or isn't yours.")
		return

	context.open_query = requested if thread else ""
	context.open_query_subject = thread[0]["subject"] if thread else ""
	context.thread = thread
	context.thread_json = frappe.as_json(thread)

	context.unread_total = (
		sum(c["unread_count"] for c in conversations) + context.general_unread
	)
