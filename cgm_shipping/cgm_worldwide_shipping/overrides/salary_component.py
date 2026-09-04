# Copyright (c) 2026, Titansoft Limited and contributors
"""Net-pay-only salary components."""

from __future__ import annotations

import frappe
from frappe import _

NET_PAY_ONLY_FIELD = "custom_include_in_net_pay_only"
NET_PAY_ONLY_CACHE_KEY = "cgm_net_pay_only_salary_components"


def get_net_pay_only_components() -> set[str]:
	"""Names of Earning components that belong in Net Pay but not Gross Pay."""

	def _fetch() -> list[str]:
		if not frappe.db.has_column("Salary Component", NET_PAY_ONLY_FIELD):
			return []
		return frappe.get_all(
			"Salary Component",
			filters={NET_PAY_ONLY_FIELD: 1},
			pluck="name",
		)

	return set(frappe.cache().get_value(NET_PAY_ONLY_CACHE_KEY, _fetch) or [])


def clear_net_pay_only_cache(doc=None, method=None) -> None:
	frappe.cache().delete_value(NET_PAY_ONLY_CACHE_KEY)


def validate_net_pay_only_component(doc, method=None) -> None:
	"""Keep the flag combination coherent, and set the flags it implies."""
	if not doc.get(NET_PAY_ONLY_FIELD):
		return

	if doc.type != "Earning":
		frappe.throw(
			_("{0} can only be set on Earning components.").format(_("Include in Net Pay Only")),
			title=_("Invalid Salary Component"),
		)

	if doc.statistical_component:
		frappe.throw(
			_(
				"{0} cannot be used with Statistical Component: a statistical component is never "
				"paid out, so it has nothing to add to Net Pay."
			).format(_("Include in Net Pay Only")),
			title=_("Invalid Salary Component"),
		)

	if doc.do_not_include_in_accounts:
		frappe.throw(
			_(
				"{0} cannot be used with Do Not Include in Accounts: the component would be added to "
				"Net Pay but excluded from the payroll Journal Entry and bank entry, so the payment "
				"would never be booked or paid."
			).format(_("Include in Net Pay Only")),
			title=_("Invalid Salary Component"),
		)

	# A Salary Structure snapshots these flags when the component is added and HRMS
	# never propagates a later change, so structures already carrying this component
	# keep the old flags and their slips will put it in Gross Pay.
	stale = frappe.get_all(
		"Salary Detail",
		filters={
			"parenttype": "Salary Structure",
			"salary_component": doc.name,
			"do_not_include_in_total": 0,
			"docstatus": ["<", 2],
		},
		pluck="parent",
		distinct=True,
	)
	if stale:
		frappe.msgprint(
			_(
				"These Salary Structures already carry {0} with Do Not Include in Total off, so it"
				" will still count towards Gross Pay on their salary slips: {1}. Remove and re-add"
				" the component row in each one."
			).format(frappe.bold(doc.name), frappe.bold(", ".join(sorted(set(stale))))),
			title=_("Salary Structures Need Updating"),
			indicator="orange",
		)

	if not doc.do_not_include_in_total:
		# The whole point of the flag is to keep the component out of Gross Pay,
		# which is what do_not_include_in_total does. Set it rather than making the
		# user tick two boxes, but say so - it changes how the slip reads.
		doc.do_not_include_in_total = 1
		frappe.msgprint(
			_("Do Not Include in Total has been enabled, so {0} stays out of Gross Pay.").format(
				frappe.bold(doc.name or doc.salary_component)
			),
			title=_("Include in Net Pay Only"),
			indicator="blue",
		)
