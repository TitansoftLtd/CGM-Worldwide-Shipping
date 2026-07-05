"""
Configuration-driven item pricing engine.

Pricing rules live on Item.custom_item_pricing_rules (Item Pricing Rule child table).
Every active rule is evaluated; the highest candidate amount becomes the quotation rate.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from erpnext import get_company_currency
from erpnext.setup.utils import get_exchange_rate
from frappe.utils import cint, flt

ITEM_PRICING_RULE_CHILD = "custom_item_pricing_rules"
QUOTATION_ITEM_PRICING_TABLE = "custom_item_pricing"

CALCULATION_PERCENTAGE = "Percentage"
CALCULATION_FIXED = "Fixed"

PRICING_ROW_FIELDS = (
	"item",
	"rule_currency",
	"calculation_type",
	"percentage_rate",
	"fixed_rate",
	"floor_rate",
	"computed_amount",
	"candidate_amount",
	"winning_rule",
	"company_amount",
)

RULE_FIELDS = (
	"currency",
	"calculation_type",
	"percentage_rate",
	"fixed_rate",
	"floor_rate",
)


def _get_value(doc, fieldname: str, default=None):
	"""Read a field from a dict, Document, or attribute-based object."""
	if isinstance(doc, dict):
		return doc.get(fieldname, default)
	if hasattr(doc, "get"):
		value = doc.get(fieldname, default)
		if value is not None or fieldname in doc:
			return value
	return getattr(doc, fieldname, default)


def validate_item_pricing_rules(item_doc) -> None:
	"""Validate each pricing rule row on an Item."""
	if not item_doc.meta.has_field(ITEM_PRICING_RULE_CHILD):
		return

	for row in item_doc.get(ITEM_PRICING_RULE_CHILD) or []:
		if not cint(row.is_active):
			continue

		if not row.currency:
			frappe.throw(
				frappe._("Active Item Pricing Rule requires a Currency."),
				title=frappe._("Invalid Pricing Rule"),
			)

		calculation_type = row.calculation_type or CALCULATION_PERCENTAGE
		if calculation_type == CALCULATION_FIXED and not flt(row.fixed_rate):
			frappe.throw(
				frappe._("Active Fixed pricing rule requires a Fixed Rate."),
				title=frappe._("Invalid Pricing Rule"),
			)
		if calculation_type == CALCULATION_PERCENTAGE and not flt(row.percentage_rate):
			frappe.throw(
				frappe._("Active Percentage pricing rule requires a Percentage Rate."),
				title=frappe._("Invalid Pricing Rule"),
			)


def get_active_item_pricing_rules(item_codes: list[str]) -> dict[str, list[dict[str, Any]]]:
	"""Batch-fetch every active pricing rule per Item in a single query."""
	unique_codes = [code for code in dict.fromkeys(item_codes) if code]
	if not unique_codes:
		return {}

	rows = frappe.get_all(
		"Item Pricing Rule",
		filters={
			"parent": ("in", unique_codes),
			"parenttype": "Item",
			"parentfield": ITEM_PRICING_RULE_CHILD,
			"is_active": 1,
		},
		fields=["parent", *RULE_FIELDS],
		order_by="parent asc, idx asc",
	)

	result: dict[str, list[dict[str, Any]]] = {}
	for row in rows:
		result.setdefault(row.parent, []).append(_normalize_rule_row(row))

	return result


def _normalize_rule_row(row) -> dict[str, Any]:
	return {
		"currency": row.currency,
		"calculation_type": row.calculation_type or CALCULATION_PERCENTAGE,
		"percentage_rate": flt(row.percentage_rate),
		"fixed_rate": flt(row.fixed_rate),
		"floor_rate": flt(row.floor_rate),
	}


def to_company_currency(
	amount: float,
	from_currency: str,
	*,
	company: str,
	quotation_currency: str,
	conversion_rate: float,
	transaction_date,
) -> float:
	"""Convert a rule-currency amount to company currency using the quotation context."""
	amount = flt(amount)
	if not amount or not from_currency:
		return amount

	company_currency = get_company_currency(company)
	if from_currency == company_currency:
		return amount

	rate = flt(conversion_rate)
	if from_currency == quotation_currency and rate:
		return flt(amount * rate)

	return convert_currency(
		amount,
		from_currency,
		company_currency,
		company=company,
		transaction_date=transaction_date,
		quotation_currency=quotation_currency,
		conversion_rate=conversion_rate,
	)


def to_quotation_currency(
	amount: float,
	from_currency: str,
	*,
	company: str,
	quotation_currency: str,
	conversion_rate: float,
	transaction_date,
) -> float:
	"""Convert a rule-currency amount to the quotation transaction currency."""
	amount = flt(amount)
	if not amount or not from_currency or from_currency == quotation_currency:
		return amount

	company_currency = get_company_currency(company)
	rate = flt(conversion_rate)

	if from_currency == company_currency and rate:
		return flt(amount / rate) if rate else 0.0

	return convert_currency(
		amount,
		from_currency,
		quotation_currency,
		company=company,
		transaction_date=transaction_date,
		quotation_currency=quotation_currency,
		conversion_rate=conversion_rate,
	)


def convert_currency(
	amount: float,
	from_currency: str,
	to_currency: str,
	*,
	company: str,
	transaction_date,
	quotation_currency: str | None = None,
	conversion_rate: float | None = None,
) -> float:
	"""Convert between currencies, preferring the quotation's conversion rate when applicable."""
	amount = flt(amount)
	if not amount or not from_currency or not to_currency or from_currency == to_currency:
		return amount

	company_currency = get_company_currency(company)
	rate = flt(conversion_rate)

	if quotation_currency and rate:
		if from_currency == quotation_currency and to_currency == company_currency:
			return flt(amount * rate)
		if from_currency == company_currency and to_currency == quotation_currency:
			return flt(amount / rate) if rate else 0.0

	exchange_rate = flt(
		get_exchange_rate(from_currency, to_currency, transaction_date, "for_selling") or 0
	)
	return flt(amount * exchange_rate)


def calculate_item_pricing_row(
	custom_value: float,
	rule: dict[str, Any],
	*,
	company: str,
	quotation_currency: str,
	conversion_rate: float,
	transaction_date,
) -> dict[str, Any]:
	"""Evaluate one pricing rule and return audit-table values."""
	rule_currency = rule["currency"]
	calculation_type = rule["calculation_type"]
	percentage_rate = flt(rule["percentage_rate"])
	fixed_rate = flt(rule["fixed_rate"])
	floor_rate = flt(rule["floor_rate"])

	if calculation_type == CALCULATION_FIXED:
		computed_amount = 0.0
		candidate_amount = fixed_rate
	else:
		computed_in_doc = (percentage_rate / 100) * flt(custom_value)
		computed_amount = convert_currency(
			computed_in_doc,
			quotation_currency,
			rule_currency,
			company=company,
			transaction_date=transaction_date,
			quotation_currency=quotation_currency,
			conversion_rate=conversion_rate,
		)
		candidate_amount = max(computed_amount, floor_rate)

	company_amount = to_company_currency(
		candidate_amount,
		rule_currency,
		company=company,
		quotation_currency=quotation_currency,
		conversion_rate=conversion_rate,
		transaction_date=transaction_date,
	)

	return {
		"rule_currency": rule_currency,
		"calculation_type": calculation_type,
		"percentage_rate": percentage_rate,
		"fixed_rate": fixed_rate,
		"floor_rate": floor_rate,
		"computed_amount": computed_amount,
		"candidate_amount": candidate_amount,
		"company_amount": company_amount,
	}


def _candidate_in_quotation_currency(
	calc: dict[str, Any],
	*,
	company: str,
	quotation_currency: str,
	conversion_rate: float,
	transaction_date,
) -> float:
	return to_quotation_currency(
		calc["candidate_amount"],
		calc["rule_currency"],
		company=company,
		quotation_currency=quotation_currency,
		conversion_rate=conversion_rate,
		transaction_date=transaction_date,
	)


def calculate_item_pricing_for_item(
	custom_value: float,
	rules: list[dict[str, Any]],
	*,
	company: str,
	quotation_currency: str,
	conversion_rate: float,
	transaction_date,
) -> tuple[list[dict[str, Any]], float]:
	"""
	Evaluate every active rule for one item and return audit rows plus the winning rate.

	The winning rate is the highest candidate amount after converting each candidate
	to the quotation currency for fair comparison across rule currencies.
	"""
	if not rules:
		return [], 0.0

	evaluated: list[tuple[dict[str, Any], float]] = []
	for rule in rules:
		calc = calculate_item_pricing_row(
			custom_value,
			rule,
			company=company,
			quotation_currency=quotation_currency,
			conversion_rate=conversion_rate,
			transaction_date=transaction_date,
		)
		quotation_candidate = _candidate_in_quotation_currency(
			calc,
			company=company,
			quotation_currency=quotation_currency,
			conversion_rate=conversion_rate,
			transaction_date=transaction_date,
		)
		evaluated.append((calc, quotation_candidate))

	winning_quotation_rate = max(quotation_candidate for _, quotation_candidate in evaluated)

	pricing_rows: list[dict[str, Any]] = []
	for calc, quotation_candidate in evaluated:
		pricing_rows.append(
			{
				**calc,
				"winning_rule": 1 if quotation_candidate == winning_quotation_rate else 0,
			}
		)

	return pricing_rows, winning_quotation_rate


def calculate_quotation_item_pricing(
	doc,
	rules: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
	"""
	Build pricing-table rows and quotation-item rate updates for a selling document.

	Rates are derived solely from Item pricing rules — never from price lists or standard rates.
	"""
	custom_value = flt(_get_value(doc, "custom_custom_value"))
	quotation_currency = _get_value(doc, "currency")
	company = _get_value(doc, "company")
	conversion_rate = flt(_get_value(doc, "conversion_rate"))
	transaction_date = _get_value(doc, "transaction_date")

	items = _get_value(doc, "items") or []
	if rules is None:
		item_codes = [_get_value(item, "item_code") for item in items if _get_value(item, "item_code")]
		rules = get_active_item_pricing_rules(item_codes)

	pricing_rows: list[dict[str, Any]] = []
	item_updates: list[dict[str, Any]] = []

	for item in items:
		item_code = _get_value(item, "item_code")
		if not item_code:
			continue

		item_rules = rules.get(item_code) or []
		if not item_rules:
			continue

		rule_rows, item_rate = calculate_item_pricing_for_item(
			custom_value,
			item_rules,
			company=company,
			quotation_currency=quotation_currency,
			conversion_rate=conversion_rate,
			transaction_date=transaction_date,
		)

		for row in rule_rows:
			pricing_rows.append({"item": item_code, **row})

		item_updates.append(
			{
				"name": _get_value(item, "name"),
				"item_code": item_code,
				"rate": item_rate,
				"qty": flt(_get_value(item, "qty") or 1),
			}
		)

	return {"pricing_rows": pricing_rows, "item_updates": item_updates}


def apply_item_pricing_to_document(doc, result: dict[str, list[dict[str, Any]]]) -> None:
	"""Write pricing rows and item line rates onto a document instance."""
	if doc.meta.has_field(QUOTATION_ITEM_PRICING_TABLE):
		doc.set(QUOTATION_ITEM_PRICING_TABLE, [])
		for row_data in result.get("pricing_rows") or []:
			doc.append(QUOTATION_ITEM_PRICING_TABLE, row_data)

	updates_by_name = {
		row["name"]: row for row in result.get("item_updates") or [] if row.get("name")
	}

	for item in doc.get("items") or []:
		update = updates_by_name.get(item.name)
		if not update:
			continue

		qty = flt(update.get("qty") or item.qty or 1)
		rate = flt(update["rate"], item.precision("rate"))
		amount = flt(rate * qty, item.precision("amount"))
		conversion_rate = flt(doc.get("conversion_rate") or 1)

		item.rate = item.net_rate = rate
		item.amount = item.net_amount = amount
		item.base_rate = item.base_net_rate = flt(
			rate * conversion_rate, item.precision("base_rate")
		)
		item.base_amount = item.base_net_amount = flt(
			amount * conversion_rate, item.precision("base_amount")
		)


@frappe.whitelist()
def get_item_pricing_rules(item_codes) -> dict[str, list[dict[str, Any]]]:
	"""Return all active pricing rules for the given item codes (batch, single query)."""
	if isinstance(item_codes, str):
		item_codes = json.loads(item_codes)
	return get_active_item_pricing_rules(item_codes)


@frappe.whitelist()
def preview_quotation_item_pricing(quotation: str | dict) -> dict[str, list[dict[str, Any]]]:
	"""Live form preview — same calculation as server-side validate."""
	if isinstance(quotation, str):
		quotation = json.loads(quotation)
	return calculate_quotation_item_pricing(quotation)
