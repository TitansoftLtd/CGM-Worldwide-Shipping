# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""CGM customer portal landing page.

Overrides Frappe's default `/portal` with a branded, shipment-focused
dashboard: greeting, KPI strip (active shipments, in transit, at port,
delivered, demurrage alerts), quick actions, an "arriving soon" panel and
a recent-shipment activity feed.

For users not yet linked to a Customer, the KPIs and lists are suppressed
and a "get connected" message is shown so the page degrades gracefully.
"""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import getdate

from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
	customer_display_name,
	customer_for_user,
	get_customer_shipments,
	status_tone,
)

no_cache = 1

_DEFAULTS = {
	"stat_active": 0,
	"stat_in_transit": 0,
	"stat_at_port": 0,
	"stat_delivered": 0,
	"stat_demurrage": 0,
	"arriving_soon": [],
	"recent_shipments": [],
}


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	context.full_width = True

	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote("/portal", safe="")
		raise frappe.Redirect

	user = frappe.session.user
	user_doc = frappe.get_cached_doc("User", user)
	context.full_name = user_doc.full_name or user_doc.first_name or user.split("@")[0]
	context.first_name = user_doc.first_name or context.full_name.split(" ")[0]
	context.user_image = user_doc.user_image
	context.greeting = _greeting_for_now(user)

	customer = customer_for_user(user)
	context.customer = customer
	context.customer_name = customer_display_name(customer)
	context.is_customer = bool(customer)

	for k, v in _DEFAULTS.items():
		context[k] = v

	if not customer:
		return

	try:
		_populate(context, customer)
	except Exception:
		frappe.log_error(title="Customer portal landing failed", message=frappe.get_traceback())


def _greeting_for_now(user):
	"""Time-of-day greeting in the user's timezone (falls back to system, UTC)."""
	from datetime import datetime
	from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

	tz_name = (
		frappe.db.get_value("User", user, "time_zone")
		or frappe.db.get_single_value("System Settings", "time_zone")
		or "UTC"
	)
	try:
		tz = ZoneInfo(tz_name)
	except ZoneInfoNotFoundError:
		tz = ZoneInfo("UTC")
	hr = datetime.now(tz=tz).hour
	if hr < 12:
		return _("Good morning")
	if hr < 17:
		return _("Good afternoon")
	return _("Good evening")


def _populate(context, customer):
	shipments = get_customer_shipments(customer)

	active = [s for s in shipments if s.custom_shipment_status != "Completed"]
	context.stat_active = len(active)
	context.stat_in_transit = sum(
		1 for s in active if s.custom_shipment_status in ("In Transit", "In Delivery")
	)
	context.stat_at_port = sum(
		1 for s in active if (s.custom_current_location or "") == "At Port"
	)
	context.stat_delivered = sum(
		1 for s in shipments if s.custom_shipment_status == "Completed"
	)

	# Demurrage exposure: containers accruing demurrage or detention on any
	# of this customer's shipments. One join beats N per-shipment queries.
	demurrage = frappe.db.sql(
		"""
		SELECT COUNT(*)
		FROM `tabContainer Tracker` ct
		JOIN `tabProject` p ON p.name = ct.project
		WHERE p.customer = %s
		  AND (IFNULL(ct.demurrage_days, 0) > 0 OR IFNULL(ct.detention_days, 0) > 0)
		""",
		(customer,),
	)
	context.stat_demurrage = (demurrage[0][0] if demurrage else 0) or 0

	# Arriving soon: not-yet-arrived shipments with an ETA, soonest first.
	today = getdate()

	def _days_until(d):
		try:
			return (getdate(d) - today).days if d else None
		except Exception:
			return None

	arriving = []
	for s in active:
		if s.custom_ata or not s.custom_eta:
			continue
		arriving.append(
			{
				"name": s.name,
				"ref": s.custom_cgm_ref_no or s.name,
				"status": s.custom_shipment_status,
				"mode": s.custom_mode_of_transport,
				"eta": s.custom_eta,
				"days_until": _days_until(s.custom_eta),
				"url": "/shipment?name=" + quote(s.name, safe=""),
			}
		)
	arriving.sort(key=lambda x: x["eta"])
	context.arriving_soon = arriving[:6]

	recent = []
	for s in shipments[:8]:
		recent.append(
			{
				"name": s.name,
				"ref": s.custom_cgm_ref_no or s.name,
				"status": s.custom_shipment_status,
				"tone": status_tone(s.custom_shipment_status),
				"bl": s.custom_bl_number,
				"url": "/shipment?name=" + quote(s.name, safe=""),
			}
		)
	context.recent_shipments = recent
