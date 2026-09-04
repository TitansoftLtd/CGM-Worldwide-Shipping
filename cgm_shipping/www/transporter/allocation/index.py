# Copyright (c) 2026, Titansoft Limited and contributors

from urllib.parse import quote

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal import (
	allocation_conversation_thread,
	get_allocation_detail,
	get_transporter_for_user,
	portal_context_base,
)

no_cache = 1


def get_context(context):
	allocation_name = (frappe.form_dict.get("name") or "").strip()

	if frappe.session.user == "Guest":
		target = "/transporter/allocation"
		if allocation_name:
			target += "?name=" + quote(allocation_name, safe="")
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(target, safe="")
		raise frappe.Redirect

	try:
		transporter = portal_context_base(context)
		if not transporter:
			return
		if not allocation_name:
			frappe.throw(_("Allocation is required."))
		context.title = _("Allocation Detail")
		context.allocation = get_allocation_detail(allocation_name)
		context.allocation_name = allocation_name

		# `?thread=` opens one conversation; without it the Messages tab lists
		# them, the same shape as the customer's /my-messages.
		_apply_open_thread(context, allocation_name)
	except frappe.Redirect:
		raise
	except frappe.DoesNotExistError:
		context.error_title = _("Allocation not found")
		context.error_message = _("This allocation does not exist or you do not have access.")
	except Exception:
		frappe.log_error(title="Transporter allocation detail failed", message=frappe.get_traceback())
		context.error_title = _("Couldn't load allocation")
		context.error_message = _("Something went wrong. CGM Worldwide Shipping has been notified.")


def _apply_open_thread(context, allocation_name: str) -> None:
	requested = (frappe.form_dict.get("thread") or "").strip()
	context.open_thread = ""
	context.open_thread_subject = ""
	context.open_thread_json = "[]"

	if not requested:
		return

	transporter = get_transporter_for_user()
	thread = allocation_conversation_thread(allocation_name, transporter, requested)
	if not thread:
		# Not this transporter's conversation - fall back to the list rather
		# than telling them whether it exists.
		return

	context.open_thread = requested
	context.open_thread_subject = thread[0]["subject"]
	context.open_thread_json = frappe.as_json(thread)
