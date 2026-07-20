"""Shipping-line free days and demurrage tier lookup."""
from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

FREE_DAYS_RULES_FIELD = "custom_shipping_line_free_days_rules"
DEMURRAGE_TIERS_FIELD = "custom_shipping_line_demurrage_tiers"

COUNT_FROM_BERTHING = "Berthing Date"
COUNT_FROM_DISCHARGE = "Discharge Date"

SUPPLIER_CHILD_TABLE_FIELDS = (
	FREE_DAYS_RULES_FIELD,
	DEMURRAGE_TIERS_FIELD,
)


@frappe.request_cache
def get_valid_destinations() -> list[str]:
	"""Read destination names from Delivery Destination master (Container Tracker display)."""
	if frappe.db.exists("DocType", "Delivery Destination"):
		return frappe.get_all("Delivery Destination", pluck="name", order_by="name asc")
	if frappe.db.table_exists("Delivery Destination"):
		return frappe.db.sql_list(
			"SELECT name FROM `tabDelivery Destination` ORDER BY name asc"
		)
	return []


def default_destination_name() -> str:
	for dest in get_valid_destinations():
		if dest.lower() == "kenya":
			return dest
	destinations = get_valid_destinations()
	return destinations[0] if destinations else "Kenya"


def supplier_has_child_table_field(fieldname: str) -> bool:
	if not frappe.db.exists("DocType", "Supplier"):
		return False
	return frappe.get_meta("Supplier").has_field(fieldname)


def get_supplier_child_rows(supplier_name: str, fieldname: str) -> list:
	"""Safely read a Supplier child table; returns [] when the field is not on the DocType."""
	if not supplier_name or not frappe.db.exists("Supplier", supplier_name):
		return []
	if not supplier_has_child_table_field(fieldname):
		return []
	return frappe.get_doc("Supplier", supplier_name).get(fieldname) or []


@frappe.request_cache
def get_valid_container_categories() -> list[str]:
	"""Read category names from Container Category doctype."""
	if not frappe.db.exists("DocType", "Container Category"):
		return []
	return frappe.get_all("Container Category", pluck="name", order_by="name asc")


def _category_name(preferred: str) -> str:
	for cat in get_valid_container_categories():
		if cat.lower() == preferred.lower():
			return cat
	return preferred


def resolve_container_category(
	cargo_type: str | None, container_number: str | None = None
) -> str:
	label = (cargo_type or "").upper()
	if container_number and "RF" in container_number.upper():
		return _category_name("Reefer")
	if "REEFER" in label or label.endswith("RF") or " RF" in label:
		return _category_name("Reefer")
	return _category_name("Standard")


def resolve_cargo_size_match_keys(cargo_size: str | None) -> frozenset[str]:
	"""Normalized size keys for tier lookup (20FT, link name, etc.)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
		resolve_cargo_size_link,
	)

	raw = (cargo_size or "").strip()
	if not raw:
		return frozenset()
	keys: set[str] = {raw}
	link = resolve_cargo_size_link(raw)
	if link:
		keys.add(link)
		if frappe.db.exists("Cargo Size", link):
			label = frappe.db.get_value("Cargo Size", link, "cargo_size")
			if label:
				keys.add(label)
	return frozenset(_normalize_size_token(k) for k in keys if k)


def _normalize_size_token(value: str) -> str:
	return (value or "").strip().upper().replace(" ", "")


def _tier_cargo_size_match_keys(tier: dict[str, Any]) -> frozenset[str]:
	raw = tier.get("cargo_size") or tier.get("cargo_type") or ""
	if not raw:
		return frozenset()
	keys: set[str] = {raw}
	if frappe.db.exists("Cargo Size", raw):
		label = frappe.db.get_value("Cargo Size", raw, "cargo_size")
		if label:
			keys.add(label)
	return frozenset(_normalize_size_token(k) for k in keys if k)


def _tier_matches_cargo_size(tier: dict[str, Any], cargo_size: str | None) -> bool:
	tier_keys = _tier_cargo_size_match_keys(tier)
	if not tier_keys:
		return False
	if "ALL" in tier_keys:
		return True
	container_keys = resolve_cargo_size_match_keys(cargo_size)
	return bool(container_keys and tier_keys & container_keys)


def _rule_row_dict(rule: Any) -> dict[str, Any]:
	return rule if isinstance(rule, dict) else rule.as_dict()


def _category_matches(rule_category: str | None, category: str) -> bool:
	rule_cat = rule_category or "All"
	return rule_cat in (category, "All")


def _match_rule_by_category(rules: list[Any], category: str) -> dict[str, Any] | None:
	matched: list[tuple[int, dict[str, Any]]] = []
	for raw in rules:
		rule = _rule_row_dict(raw)
		if not _category_matches(rule.get("container_category"), category):
			continue
		score = 2 if rule.get("container_category") == category else 1
		matched.append((score, rule))
	if not matched:
		return None
	matched.sort(key=lambda item: item[0], reverse=True)
	return matched[0][1]


def get_free_days_rule(shipping_line: str, category: str) -> dict[str, Any] | None:
	"""Return the best free-days rule for a shipping line and container category."""
	if not shipping_line:
		return None
	rules = get_supplier_child_rows(shipping_line, FREE_DAYS_RULES_FIELD)
	if not rules:
		return None
	return _match_rule_by_category(rules, category)


def build_rate_source_label(
	shipping_line: str, category: str, rule: dict[str, Any] | None
) -> str:
	if not rule:
		return shipping_line or ""
	free_days = rule.get("free_days")
	rule_category = rule.get("container_category") or category
	return f"{shipping_line} {rule_category} ({free_days}-day free)"


def get_demurrage_tiers(
	shipping_line: str, cargo_size: str | None
) -> list[dict[str, Any]]:
	if not shipping_line:
		return []
	rows = get_supplier_child_rows(shipping_line, DEMURRAGE_TIERS_FIELD)
	matched = [
		_rule_row_dict(r)
		for r in rows
		if _tier_matches_cargo_size(_rule_row_dict(r), cargo_size)
		and "ALL" not in _tier_cargo_size_match_keys(_rule_row_dict(r))
	]
	if not matched:
		matched = [
			_rule_row_dict(r)
			for r in rows
			if "ALL" in _tier_cargo_size_match_keys(_rule_row_dict(r))
		]
	return sorted(matched, key=lambda r: int(r.get("from_day") or 1))


def tier_for_day(day_no: int, tiers: list[dict[str, Any]]) -> dict[str, Any] | None:
	for tier in tiers:
		from_day = int(tier.get("from_day") or 1)
		to_day = int(tier.get("to_day") or 0)
		if to_day == 0 and day_no >= from_day:
			return tier
		if to_day and from_day <= day_no <= to_day:
			return tier
	return None


def daily_rate_for_day(day_no: int, tiers: list[dict[str, Any]]) -> float:
	tier = tier_for_day(day_no, tiers)
	return flt(tier.get("daily_rate")) if tier else 0.0


def tier_currency_for_day(
	day_no: int, tiers: list[dict[str, Any]], fallback: str | None = None
) -> str | None:
	tier = tier_for_day(day_no, tiers)
	if tier and tier.get("currency"):
		return tier["currency"]
	return fallback


def calculate_tiered_charge(chargeable_days: int, tiers: list[dict[str, Any]]) -> float:
	if chargeable_days <= 0 or not tiers:
		return 0.0
	total = 0.0
	for day_no in range(1, chargeable_days + 1):
		total += daily_rate_for_day(day_no, tiers)
	return flt(total)


# Backward-compatible alias used by container_charges.
def get_charge_tiers(
	shipping_line: str, _charge_type: str, cargo_size: str | None
) -> list[dict]:
	return get_demurrage_tiers(shipping_line, cargo_size)
