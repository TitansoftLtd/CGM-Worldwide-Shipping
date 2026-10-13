"""Multicurrency for the Material Request -> Funding Request -> Journal Entry chain.

CGM pays some operational expenses in foreign currency: shipping line charges and
KPA charges are billed in USD, and the company holds USD bank accounts for them.
Before this, every Currency field in the chain rendered in the company currency
(KES) because none of them carried an `options` currency field, so a USD request
had to be converted by hand before it was typed in, and the figure the approver
saw had no record of the rate it came from.

The shape of the solution:

* A Material Request line carries its own `custom_currency` and an estimated
  `custom_exchange_rate`. `rate` and `amount` are now read in the line's own
  currency, and `custom_base_amount` holds the company-currency equivalent.
* Those travel to the Funding Request row, which keeps `requested_amount` and
  `approved_amount` in the row currency and mirrors them into `base_*` twins.
* The Funding Request header totals keep their existing meaning - company
  currency - so approval, payment capping and `outstanding` are unchanged. A
  `currency_totals` line shows what was asked for in each currency.
* The Journal Entry fetches the *live* rate on the day it is created, because the
  estimate on the request is weeks old by the time Finance pays and the ledger has
  to carry the real rate. Finance picks the bank account at that moment.

The estimate and the payment rate are deliberately two different numbers. The
estimate exists so an approver can see a company-currency figure; the payment rate
exists because that is what actually left the bank. Where they differ the gap shows
up as a real variance between `base_approved_amount` and `base_funded_amount`,
which is accurate rather than something to hide. Row closure is therefore decided
on the *foreign* amount, so a rate movement cannot strand a fully paid row.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from .constants import MATERIAL_REQUEST_TYPE_OPERATIONAL

#: Rate precision. Frankfurter quotes 4-5 significant decimals; 9 leaves room and
#: matches the `custom_exchange_rate` field precision.
RATE_PRECISION = 9


def company_currency(company: str | None) -> str:
	"""The company's own currency, falling back to the global default."""
	if company:
		currency = frappe.get_cached_value("Company", company, "default_currency")
		if currency:
			return currency
	return frappe.defaults.get_global_default("currency") or "KES"


def is_multicurrency(doc) -> bool:
	"""True when this Material Request is allowed foreign-currency lines."""
	if not doc:
		return False
	# Operational Expense is the only type that funds through a Funding Request
	# rather than a Purchase Order, so it is the only one where a foreign currency
	# has anywhere to go.
	if doc.get("material_request_type") != MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return False
	return bool(doc.get("custom_multicurrency"))


def live_exchange_rate(
	from_currency: str, to_currency: str, on_date: str | None = None
) -> float:
	"""The most current rate available, service first and stored records second.

	This deliberately inverts ERPNext's own order. `get_exchange_rate` looks for a
	Currency Exchange record before it asks the service, and this site has
	`allow_stale` switched on, so a single record entered once would pin every
	future payment to that day's rate for good. CGM pays at today's rate, so the
	Currency Exchange Settings service is asked first and stored records are the
	fallback for when it cannot be reached.

	Returns 0.0 rather than raising when no rate can be had at all, so the caller
	decides what to do. That matters: posting at a zero rate would write a
	zero-value Journal Entry, which is worse than refusing to build one.
	"""
	if not from_currency or not to_currency or from_currency == to_currency:
		return 1.0
	on_date = on_date or frappe.utils.nowdate()
	rate = _service_exchange_rate(from_currency, to_currency, on_date)
	if rate > 0:
		return rate
	return _stored_exchange_rate(from_currency, to_currency, on_date)


def _service_exchange_rate(from_currency: str, to_currency: str, on_date: str) -> float:
	"""Ask the provider configured in Currency Exchange Settings.

	Shares ERPNext's six-hour cache key, so turning the order around does not mean
	twice the calls to the provider.
	"""
	try:
		settings = frappe.get_cached_doc("Currency Exchange Settings")
		if settings.get("disabled"):
			return 0.0

		cache = frappe.cache()
		key = f"currency_exchange_rate_{on_date}:{from_currency}:{to_currency}"
		cached = cache.get(key)
		if cached:
			return flt(cached, RATE_PRECISION)

		import requests

		from erpnext.setup.utils import format_ces_api

		params_for_url = {
			"transaction_date": on_date,
			"from_currency": from_currency,
			"to_currency": to_currency,
		}
		response = requests.get(
			format_ces_api(settings.api_endpoint, params_for_url),
			params={row.key: format_ces_api(row.value, params_for_url) for row in settings.req_params},
			timeout=10,
		)
		response.raise_for_status()
		value = response.json()
		for result_key in settings.result_key:
			value = value[format_ces_api(str(result_key.key), params_for_url)]
		rate = flt(value, RATE_PRECISION)
		if rate > 0:
			cache.setex(name=key, time=21600, value=rate)
		return rate
	except Exception:
		frappe.log_error(
			title="live_exchange_rate: service",
			message=f"{from_currency}->{to_currency} on {on_date}: {frappe.get_traceback()}",
		)
		return 0.0


def _stored_exchange_rate(from_currency: str, to_currency: str, on_date: str) -> float:
	"""The newest Currency Exchange record on or before the date."""
	rows = frappe.get_all(
		"Currency Exchange",
		filters={
			"from_currency": from_currency,
			"to_currency": to_currency,
			"date": ["<=", on_date],
		},
		fields=["exchange_rate"],
		order_by="date desc",
		limit=1,
	)
	return flt(rows[0].exchange_rate, RATE_PRECISION) if rows else 0.0


def currency_totals(pairs: list[tuple[str, float]]) -> dict[str, float]:
	"""Sum amounts by currency, dropping currencies that total nothing."""
	totals: dict[str, float] = {}
	for currency, amount in pairs:
		if not currency:
			continue
		totals[currency] = flt(totals.get(currency, 0)) + flt(amount)
	return {currency: total for currency, total in totals.items() if abs(total) > 0.005}


def format_currency_totals(totals: dict[str, float], label: str | None = None) -> str:
	"""One line per currency, company currency first, then alphabetical.

	Plain text rather than HTML: this lands in a Small Text field, and
	`clean_html` would strip any styling anyway.
	"""
	if not totals:
		return ""
	base = frappe.defaults.get_global_default("currency")
	ordered = sorted(totals, key=lambda c: (c != base, c))
	# The ISO code and a plain number. Passing the currency to `fmt_money` would
	# add its symbol as well, giving "USD $ 1,000.00".
	lines = [f"{currency} {frappe.utils.fmt_money(totals[currency])}" for currency in ordered]
	if label:
		return f"{label}: " + "   ".join(lines)
	return "\n".join(lines)


def normalize_material_request_currencies(doc) -> None:
	"""Settle every line's currency, rate and company-currency amount.

	Called from the Material Request validate hook. Single-currency requests are
	forced back to the company currency at rate 1, so unticking the box cannot
	leave a stray foreign line behind, and a request that never touches
	multicurrency behaves exactly as it did before.
	"""
	base = company_currency(doc.get("company"))
	multi = is_multicurrency(doc)

	for row in doc.get("items") or []:
		if not multi or not row.get("custom_currency"):
			row.custom_currency = base
		if row.custom_currency == base:
			row.custom_exchange_rate = 1
		elif flt(row.get("custom_exchange_rate")) <= 0:
			# An unusable rate would silently value the line at zero in company
			# currency, so take today's rate rather than guess or accept it.
			fetched = live_exchange_rate(row.custom_currency, base, doc.get("transaction_date"))
			if fetched <= 0:
				frappe.throw(
					_("Enter an Exchange Rate for row {0}: {1} to {2} could not be fetched.").format(
						row.idx, frappe.bold(row.custom_currency), frappe.bold(base)
					)
				)
			row.custom_exchange_rate = fetched
		row.custom_base_amount = flt(flt(row.get("amount")) * flt(row.custom_exchange_rate), 2)

	if doc.meta.has_field("custom_base_total"):
		doc.custom_base_total = flt(
			sum(flt(row.get("custom_base_amount")) for row in doc.get("items") or []), 2
		)
	if doc.meta.has_field("custom_currency_totals"):
		totals = currency_totals(
			[(row.get("custom_currency"), row.get("amount")) for row in doc.get("items") or []]
		)
		doc.custom_currency_totals = format_currency_totals(totals) if multi else ""


def material_request_currency_totals(material_request: str) -> list[dict]:
	"""A Material Request split into one entry per currency.

	One request may hold lines in several currencies. It cannot be *paid* as one
	thing, though: a Journal Entry takes money out of a single bank account held in
	a single currency. So the request becomes one Funding Request row per currency,
	each approved on its own and each paid from the account that matches it.

	Returns the company currency first, then alphabetically, so a request reads the
	same way every time regardless of the order the lines were typed in.

	Each entry carries the currency, the amount in that currency, the rate used and
	the company-currency equivalent. The rate is the one on the lines: where lines
	in the same currency disagree, the amount-weighted average is used, since that
	is the rate that reproduces the company-currency figure the approver was shown.
	"""
	if not material_request:
		return []
	company = frappe.db.get_value("Material Request", material_request, "company")
	base = company_currency(company)
	rows = frappe.get_all(
		"Material Request Item",
		filters={"parent": material_request},
		fields=["custom_currency", "custom_exchange_rate", "amount", "custom_base_amount"],
		order_by="idx",
	)

	buckets: dict[str, dict] = {}
	for row in rows:
		amount = flt(row.amount)
		if not amount:
			continue
		currency = row.custom_currency or base
		rate = flt(row.custom_exchange_rate) or (1.0 if currency == base else 0.0)
		bucket = buckets.setdefault(currency, {"amount": 0.0, "base_amount": 0.0})
		bucket["amount"] += amount
		bucket["base_amount"] += flt(row.custom_base_amount) or (amount * rate)

	if not buckets:
		# No priced lines: fall back to the legacy header amount in company currency
		# so an old request still funds.
		legacy = _legacy_requested_amount(material_request)
		if not legacy:
			return []
		buckets = {base: {"amount": legacy, "base_amount": legacy}}

	out = []
	for currency in sorted(buckets, key=lambda c: (c != base, c)):
		bucket = buckets[currency]
		amount = flt(bucket["amount"], 2)
		base_amount = flt(bucket["base_amount"], 2)
		rate = 1.0 if currency == base else flt(base_amount / amount, RATE_PRECISION) if amount else 1.0
		out.append(
			{
				"currency": currency,
				"amount": amount,
				"exchange_rate": rate,
				"base_amount": base_amount,
			}
		)
	return out


def _legacy_requested_amount(material_request: str) -> float:
	"""Header amount on requests raised before the Items table carried figures."""
	value = frappe.db.get_value(
		"Material Request", material_request, "custom_requested_amount"
	)
	return flt(value)
