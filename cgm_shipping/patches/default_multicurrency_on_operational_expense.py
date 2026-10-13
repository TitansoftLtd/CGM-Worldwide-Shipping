"""Tick Multicurrency on Operational Expense requests that already exist.

Why: Operational Expense is the only request type funded by Journal Entry rather
than a Purchase Order, and it is where CGM's foreign-currency spending lives -
shipping line and KPA charges are billed in USD. Leaving the box unticked by
default meant every one of those requests started out unable to express the
currency it was actually in, and somebody had to remember to tick it.

A DocField `default` only applies to documents created after it ships, so without
this a request raised last week would behave differently from one raised today, on
the same form, for the same kind of spending. That is the sort of inconsistency
people quite reasonably report as a bug.

What: sets `custom_multicurrency` on existing Operational Expense Material
Requests. Nothing recalculates: every line on them already carries the company
currency at rate 1 from `backfill_funding_currency_fields`, so the amounts, the
totals and anything posted stay exactly as they are. The only change is that the
Currency column becomes meaningful on those requests.

Deliberately limited to Operational Expense. Purchase and Subcontracting fund
through a Purchase Order raised in the company currency, and the flag is ignored
for them anyway.

Written with SQL because this includes submitted and cancelled documents that the
ORM would refuse to save, and because the flag drives display rather than any
posted figure.

Idempotent. Retire per docs/guides/patches.md once staging and production Patch Log
show it.
"""

import frappe

REQUEST_TYPE = "Operational Expense"


def execute():
	if not frappe.db.has_column("Material Request", "custom_multicurrency"):
		print("custom_multicurrency is not on this site yet; nothing to do.")
		return

	pending = frappe.db.sql(
		"""
		select count(*)
		from `tabMaterial Request`
		where material_request_type = %(request_type)s
			and ifnull(custom_multicurrency, 0) = 0
		""",
		{"request_type": REQUEST_TYPE},
	)[0][0]

	if not pending:
		print(f"No {REQUEST_TYPE} request needs the multicurrency flag.")
		return

	frappe.db.sql(
		"""
		update `tabMaterial Request`
		set custom_multicurrency = 1
		where material_request_type = %(request_type)s
			and ifnull(custom_multicurrency, 0) = 0
		""",
		{"request_type": REQUEST_TYPE},
	)
	frappe.db.commit()
	print(f"Multicurrency switched on for {pending} existing {REQUEST_TYPE} request(s).")
