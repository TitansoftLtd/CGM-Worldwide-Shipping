"""Stamp existing requests with the company currency so nothing reads as blank.

Why: multicurrency added `custom_currency` to Material Request Item and `currency`
plus the `base_*` twins to the Funding Request rows. Every record written before
that has them empty. The code already treats empty as "company currency", so this
is not a correctness fix - it is so the Currency column on an old request shows KES
rather than nothing, and so the company-currency twins hold real figures instead of
being derived on the fly every time a total is recomputed.

What: fills the currency with the owning company's own currency, the rate with 1,
and each base twin with the amount it mirrors. At rate 1 the twin is the same
number, which is exactly why this is safe to run over historical data: no figure
changes, only fields that were empty get a value.

Deliberately touches nothing that already has a currency set. If a request was
raised in USD before this ran - which cannot have happened, since the field did not
exist - it would be left alone rather than forced to KES.

Written with SQL rather than the ORM because these are derived display fields with
no hooks behind them, and the Funding Request rows include submitted documents that
the ORM would refuse to save.

Idempotent. Retire per docs/guides/patches.md once staging and production Patch Log
show it.
"""

import frappe
from frappe.modules.utils import sync_customizations


def _company_currency_map() -> dict[str, str]:
	return {
		row.name: row.default_currency
		for row in frappe.get_all("Company", fields=["name", "default_currency"])
		if row.default_currency
	}


def execute():
	# `sync_customizations()` runs after post-model-sync patches, so on the migrate
	# that first ships these fields the columns do not exist yet. Pull this app's
	# customizations in before touching them.
	sync_customizations("cgm_shipping")
	if not frappe.db.has_column("Material Request Item", "custom_currency"):
		print("Currency fields are not on this site yet; nothing to backfill.")
		return

	currencies = _company_currency_map()
	if not currencies:
		print("No company has a default currency; nothing to backfill.")
		return

	item_rows = 0
	for company, currency in currencies.items():
		item_rows += frappe.db.sql(
			"""
			select count(*)
			from `tabMaterial Request Item` item
			inner join `tabMaterial Request` mr on mr.name = item.parent
			where mr.company = %(company)s
				and coalesce(item.custom_currency, '') = ''
			""",
			{"company": company},
		)[0][0]
		frappe.db.sql(
			"""
			update `tabMaterial Request Item` item
			inner join `tabMaterial Request` mr on mr.name = item.parent
			set item.custom_currency = %(currency)s,
				item.custom_exchange_rate = 1,
				item.custom_base_amount = coalesce(item.amount, 0)
			where mr.company = %(company)s
				and coalesce(item.custom_currency, '') = ''
			""",
			{"company": company, "currency": currency},
		)
		frappe.db.sql(
			"""
			update `tabMaterial Request`
			set custom_base_total = (
				select coalesce(sum(coalesce(amount, 0)), 0)
				from `tabMaterial Request Item`
				where parent = `tabMaterial Request`.name
			)
			where company = %(company)s
				and coalesce(custom_base_total, 0) = 0
			""",
			{"company": company},
		)

	fr_rows = 0
	if frappe.db.has_column("Funding Request Material Request", "currency"):
		for company, currency in currencies.items():
			fr_rows += frappe.db.sql(
				"""
				select count(*)
				from `tabFunding Request Material Request` row
				inner join `tabFunding Request` fr on fr.name = row.parent
				where fr.company = %(company)s
					and coalesce(row.currency, '') = ''
				""",
				{"company": company},
			)[0][0]
			frappe.db.sql(
				"""
				update `tabFunding Request Material Request` row
				inner join `tabFunding Request` fr on fr.name = row.parent
				set row.currency = %(currency)s,
					row.exchange_rate = 1,
					row.base_requested_amount = coalesce(row.requested_amount, 0),
					row.base_approved_amount = coalesce(row.approved_amount, 0),
					row.base_funded_amount = coalesce(row.funded_amount, 0)
				where fr.company = %(company)s
					and coalesce(row.currency, '') = ''
				""",
				{"company": company, "currency": currency},
			)

	frappe.db.commit()
	print(
		f"Backfilled currency on {item_rows} Material Request Item(s) and "
		f"{fr_rows} Funding Request row(s) across {len(currencies)} company(s)."
	)
