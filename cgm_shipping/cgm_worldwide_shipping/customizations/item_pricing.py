"""
Configuration-driven item pricing engine.

Pricing rules live on Item.custom_item_pricing_rules (Item Pricing Rule child table).
Every rule is evaluated; the highest amount in quotation currency becomes the item rate.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from erpnext import get_company_currency
from frappe.utils import flt

ITEM_PRICING_RULE_CHILD = "custom_item_pricing_rules"
QUOTATION_ITEM_PRICING_TABLE = "custom_item_pricing"

CALCULATION_PERCENTAGE = "Percentage"
CALCULATION_FIXED = "Fixed"
RULE_TYPE_FIXED = "Fixed Rate"

PRICING_ROW_FIELDS = (
	"item",
	"rule_type",
	"percentage_rate",
	"fixed_rate",
	"rule_currency",
	"exchange_rate_used",
	"calculated_amount",
	"final_applied_rate",
)

RULE_FIELDS = (
	"currency",
	"calculation_type",
	"percentage_rate",
	"fixed_rate",
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
		if not row.currency:
			frappe.throw(
				frappe._("Item Pricing Rule requires a Currency."),
				title=frappe._("Invalid Pricing Rule"),
			)

		calculation_type = row.calculation_type or CALCULATION_PERCENTAGE
		if calculation_type == CALCULATION_FIXED and not flt(row.fixed_rate):
			frappe.throw(
				frappe._("Fixed pricing rule requires a Fixed Rate."),
				title=frappe._("Invalid Pricing Rule"),
			)
		if calculation_type == CALCULATION_PERCENTAGE and not flt(row.percentage_rate):
			frappe.throw(
				frappe._("Percentage pricing rule requires a Percentage Rate."),
				title=frappe._("Invalid Pricing Rule"),
			)


def get_item_pricing_rules_for_items(item_codes: list[str]) -> dict[str, list[dict[str, Any]]]:
	"""Batch-fetch every pricing rule per Item in a single query."""
	unique_codes = [code for code in dict.fromkeys(item_codes) if code]
	if not unique_codes:
		return {}

	rows = frappe.get_all(
		"Item Pricing Rule",
		filters={
			"parent": ("in", unique_codes),
			"parenttype": "Item",
			"parentfield": ITEM_PRICING_RULE_CHILD,
		},
		fields=["parent", *RULE_FIELDS],
		order_by="parent asc, idx asc",
	)

	result: dict[str, list[dict[str, Any]]] = {}
	for row in rows:
		result.setdefault(row.parent, []).append(_normalize_rule_row(row))

	return result


def get_active_item_pricing_rules(item_codes: list[str]) -> dict[str, list[dict[str, Any]]]:
	"""Backward-compatible alias for callers that batch-fetch item pricing rules."""
	return get_item_pricing_rules_for_items(item_codes)


def _normalize_rule_row(row) -> dict[str, Any]:
	return {
		"currency": row.currency,
		"calculation_type": row.calculation_type or CALCULATION_PERCENTAGE,
		"percentage_rate": flt(row.percentage_rate),
		"fixed_rate": flt(row.fixed_rate),
	}


def _rule_type_label(calculation_type: str) -> str:
	return RULE_TYPE_FIXED if calculation_type == CALCULATION_FIXED else CALCULATION_PERCENTAGE


def calculate_rule_amount(
	custom_value: float,
	rule: dict[str, Any],
	*,
	quotation_currency: str,
	company_currency: str,
	conversion_rate: float,
	transaction_date: str | None = None,
) -> float:
	"""Return the rule amount in quotation currency."""
	calculation_type = rule["calculation_type"]

	if calculation_type == CALCULATION_FIXED:
		fixed_rate = flt(rule["fixed_rate"])
		rule_currency = rule["currency"]
		exchange_rate = flt(conversion_rate)

		if rule.get("fx_to_quotation") is not None:
			return flt(fixed_rate * flt(rule["fx_to_quotation"]))

		if rule_currency == quotation_currency:
			return fixed_rate
		if rule_currency == company_currency:
			return flt(fixed_rate / exchange_rate) if exchange_rate else 0.0

		fx = _exchange_rate(rule_currency, quotation_currency, transaction_date)
		return flt(fixed_rate * fx) if fx else 0.0

	return (flt(rule["percentage_rate"]) / 100) * flt(custom_value)


def _exchange_rate(
	from_currency: str | None,
	to_currency: str | None,
	transaction_date: str | None = None,
) -> float:
	from_currency = (from_currency or "").strip()
	to_currency = (to_currency or "").strip()
	if not from_currency or not to_currency:
		return 0.0
	if from_currency == to_currency:
		return 1.0
	try:
		from erpnext.setup.utils import get_exchange_rate

		return flt(get_exchange_rate(from_currency, to_currency, transaction_date))
	except Exception:
		return 0.0


def _attach_fx_to_rules(
	rules: dict[str, list[dict[str, Any]]],
	*,
	quotation_currency: str | None,
	company: str | None,
	transaction_date: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
	"""Attach rule→quotation FX so clients can convert Fixed rates correctly."""
	quotation_currency = (quotation_currency or "").strip()
	if not quotation_currency:
		return rules

	for item_rules in rules.values():
		for rule in item_rules:
			rule["fx_to_quotation"] = _exchange_rate(
				rule.get("currency"), quotation_currency, transaction_date
			)
	return rules


def calculate_item_pricing_for_item(
	custom_value: float,
	rules: list[dict[str, Any]],
	*,
	quotation_currency: str,
	company_currency: str,
	conversion_rate: float,
	transaction_date: str | None = None,
) -> tuple[dict[str, Any] | None, float]:
	"""
	Evaluate every rule for one item and return the winning audit row plus the final rate.

	The winning rate is the highest calculated amount in quotation currency.
	When every rule evaluates to zero (e.g. no customs value yet), the first rule is
	still returned so the Item Pricing table shows that the item is rule-driven.
	"""
	if not rules:
		return None, 0.0

	winning_rule = None
	winning_amount: float | None = None

	for rule in rules:
		amount = calculate_rule_amount(
			custom_value,
			rule,
			quotation_currency=quotation_currency,
			company_currency=company_currency,
			conversion_rate=conversion_rate,
			transaction_date=transaction_date,
		)
		if winning_amount is None or amount > winning_amount:
			winning_amount = amount
			winning_rule = rule

	if not winning_rule:
		return None, 0.0

	winning_amount = flt(winning_amount)
	calculation_type = winning_rule["calculation_type"]
	audit_row = {
		"rule_type": _rule_type_label(calculation_type),
		"percentage_rate": flt(winning_rule["percentage_rate"]),
		"fixed_rate": flt(winning_rule["fixed_rate"]),
		"rule_currency": winning_rule["currency"],
		"exchange_rate_used": flt(
			winning_rule.get("fx_to_quotation")
			if winning_rule.get("fx_to_quotation") is not None
			else conversion_rate
		),
		"calculated_amount": winning_amount,
		"final_applied_rate": winning_amount,
	}

	return audit_row, winning_amount


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
	company_currency = get_company_currency(company)
	conversion_rate = flt(_get_value(doc, "conversion_rate"))
	transaction_date = _get_value(doc, "transaction_date") or _get_value(doc, "posting_date")

	items = _get_value(doc, "items") or []
	if rules is None:
		item_codes = [_get_value(item, "item_code") for item in items if _get_value(item, "item_code")]
		rules = get_item_pricing_rules_for_items(item_codes)
		rules = _attach_fx_to_rules(
			rules,
			quotation_currency=quotation_currency,
			company=company,
			transaction_date=transaction_date,
		)

	pricing_rows: list[dict[str, Any]] = []
	item_updates: list[dict[str, Any]] = []

	for item in items:
		item_code = _get_value(item, "item_code")
		if not item_code:
			continue

		item_rules = rules.get(item_code) or []
		if not item_rules:
			continue

		audit_row, item_rate = calculate_item_pricing_for_item(
			custom_value,
			item_rules,
			quotation_currency=quotation_currency,
			company_currency=company_currency,
			conversion_rate=conversion_rate,
			transaction_date=transaction_date,
		)
		if not audit_row:
			continue

		pricing_rows.append({"item": item_code, **audit_row})
		item_updates.append(
			{
				"name": _get_value(item, "name"),
				"item_code": item_code,
				"rate": item_rate,
			}
		)

	return {"pricing_rows": pricing_rows, "item_updates": item_updates}


def apply_item_pricing_to_document(doc, result: dict[str, list[dict[str, Any]]]) -> None:
	"""Write audit rows and item line rates onto a document instance."""
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
		item.rate = flt(update["rate"], item.precision("rate"))


@frappe.whitelist()
def get_item_pricing_rules(
	item_codes,
	quotation_currency: str | None = None,
	company: str | None = None,
	transaction_date: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
	"""Return all pricing rules for the given item codes (batch, single query)."""
	if isinstance(item_codes, str):
		item_codes = json.loads(item_codes)
	rules = get_item_pricing_rules_for_items(item_codes)
	return _attach_fx_to_rules(
		rules,
		quotation_currency=quotation_currency,
		company=company,
		transaction_date=transaction_date,
	)


@frappe.whitelist()
def preview_quotation_item_pricing(quotation: str | dict) -> dict[str, list[dict[str, Any]]]:
	"""Live form preview — same calculation as server-side validate."""
	if isinstance(quotation, str):
		quotation = json.loads(quotation)
	return calculate_quotation_item_pricing(quotation)
