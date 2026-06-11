"""Shipping-line demurrage/detention rules and tiered rate lookup."""
from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

FREE_DAYS_RULES_FIELD = "custom_shipping_line_free_days_rules"
DEMURRAGE_TIERS_FIELD = "custom_shipping_line_demurrage_tiers"
DETENTION_TIERS_FIELD = "custom_shipping_line_detention_tiers"

COUNT_FROM_BERTHING = "Berthing Date"
COUNT_FROM_DISCHARGE = "Discharge Date"


@frappe.request_cache
def get_valid_destinations() -> list[str]:
	"""Read destination names from Delivery Destination doctype."""
	if not frappe.db.exists("DocType", "Delivery Destination"):
		return []
	return frappe.get_all("Delivery Destination", pluck="name", order_by="name asc")


@frappe.request_cache
def get_valid_container_categories() -> list[str]:
	"""Read category names from Container Category doctype."""
	if not frappe.db.exists("DocType", "Container Category"):
		return []
	return frappe.get_all("Container Category", pluck="name", order_by="name asc")


def default_destination_name() -> str:
	for dest in get_valid_destinations():
		if dest.lower() == "kenya":
			return dest
	destinations = get_valid_destinations()
	return destinations[0] if destinations else "Kenya"


def _category_name(preferred: str) -> str:
	for cat in get_valid_container_categories():
		if cat.lower() == preferred.lower():
			return cat
	return preferred


def resolve_container_category(
	type_of_container: str | None, container_number: str | None = None
) -> str:
	label = (type_of_container or "").upper()
	if container_number and "RF" in container_number.upper():
		return _category_name("Reefer")
	if "REEFER" in label or label.endswith("RF") or " RF" in label:
		return _category_name("Reefer")
	return _category_name("Standard")


def resolve_container_type_key(type_of_container: str | None) -> str:
	valid_types = (
		frappe.get_all("Container Type", pluck="container_type", order_by="name asc")
		if frappe.db.exists("DocType", "Container Type")
		else []
	)
	if not type_of_container:
		return "All"
	label = type_of_container.upper()
	if "REEFER" in label or label.endswith("RF"):
		for size in valid_types:
			if size.upper() == "REEFER":
				return size
		return "All"
	for size in sorted(valid_types, key=len, reverse=True):
		key = size.upper()
		if key.replace("FT", "") in label.replace(" ", "") or key in label:
			return size
	if frappe.db.exists("Container Type", type_of_container):
		name = (
			frappe.db.get_value("Container Type", type_of_container, "container_type") or ""
		).upper()
		for size in sorted(valid_types, key=len, reverse=True):
			key = size.upper()
			if key.replace("FT", "") in name or key in name:
				return size
		if "REEFER" in name:
			for size in valid_types:
				if size.upper() == "REEFER":
					return size
	return "All"


def _match_rule(
	rules: list[dict[str, Any]],
	destination: str,
	category: str,
) -> dict[str, Any] | None:
	candidates: list[tuple[int, dict[str, Any]]] = []
	for rule in rules:
		region = rule.get("destination_region") or "Default"
		rule_cat = rule.get("container_category") or "All"
		if region not in (destination, "Default"):
			continue
		if rule_cat not in (category, "All"):
			continue
		score = 0
		if region == destination:
			score += 2
		if rule_cat == category:
			score += 1
		candidates.append((score, rule))
	if not candidates:
		return None
	candidates.sort(key=lambda item: item[0], reverse=True)
	return candidates[0][1]


def get_free_days_rule(
	shipping_line: str,
	destination: str,
	category: str,
) -> dict[str, Any] | None:
	if not shipping_line or not frappe.db.exists("Supplier", shipping_line):
		return None
	supplier = frappe.get_doc("Supplier", shipping_line)
	rules = supplier.get(FREE_DAYS_RULES_FIELD) or []
	if not rules:
		return _legacy_supplier_rule(shipping_line)
	return _match_rule(rules, destination or default_destination_name(), category)


def _legacy_supplier_rule(shipping_line: str) -> dict[str, Any] | None:
	meta = frappe.get_meta("Supplier")
	if not meta.has_field("custom_demurrage_free_days"):
		return None
	values = frappe.db.get_value(
		"Supplier",
		shipping_line,
		["custom_demurrage_free_days", "custom_detention_free_days"],
		as_dict=True,
	)
	if not values or not values.get("custom_demurrage_free_days"):
		return None
	return {
		"free_days": int(values.custom_demurrage_free_days),
		"detention_free_days": values.get("custom_detention_free_days"),
		"count_from": COUNT_FROM_DISCHARGE,
		"destination_region": "Default",
		"container_category": "All",
	}


def build_rate_source_label(
	shipping_line: str, destination: str, category: str, rule: dict[str, Any] | None
) -> str:
	if not rule:
		return shipping_line or ""
	region = rule.get("destination_region") or destination
	free_days = rule.get("free_days")
	return f"{shipping_line} {region} {category} ({free_days}-day)"


def get_charge_tiers(
	shipping_line: str, charge_type: str, container_type_key: str
) -> list[dict[str, Any]]:
	if not shipping_line or not frappe.db.exists("Supplier", shipping_line):
		return []
	field = DEMURRAGE_TIERS_FIELD if charge_type == "demurrage" else DETENTION_TIERS_FIELD
	supplier = frappe.get_doc("Supplier", shipping_line)
	rows = supplier.get(field) or []
	if not rows and charge_type == "demurrage":
		return _legacy_flat_demurrage_tier(shipping_line, container_type_key)
	if not rows and charge_type == "detention":
		return _legacy_flat_detention_tier(shipping_line, container_type_key)
	matched = [r for r in rows if r.container_type in (container_type_key, "All")]
	if not matched:
		matched = [r for r in rows if r.container_type == "All"]
	return sorted(matched, key=lambda r: int(r.from_day or 1))


def _legacy_flat_demurrage_tier(shipping_line: str, container_type_key: str) -> list[dict]:
	meta = frappe.get_meta("Supplier")
	if not meta.has_field("custom_demurrage_daily_rate"):
		return []
	rate = frappe.db.get_value("Supplier", shipping_line, "custom_demurrage_daily_rate")
	if not rate:
		return []
	return [
		{
			"container_type": container_type_key,
			"from_day": 1,
			"to_day": 0,
			"daily_rate": flt(rate),
		}
	]


def _legacy_flat_detention_tier(shipping_line: str, container_type_key: str) -> list[dict]:
	meta = frappe.get_meta("Supplier")
	if not meta.has_field("custom_detention_daily_rate"):
		return []
	rate = frappe.db.get_value("Supplier", shipping_line, "custom_detention_daily_rate")
	if not rate:
		return []
	return [
		{
			"container_type": container_type_key,
			"from_day": 1,
			"to_day": 0,
			"daily_rate": flt(rate),
		}
	]


def daily_rate_for_day(day_no: int, tiers: list[dict[str, Any]]) -> float:
	for tier in tiers:
		from_day = int(tier.get("from_day") or 1)
		to_day = int(tier.get("to_day") or 0)
		if to_day == 0 and day_no >= from_day:
			return flt(tier.get("daily_rate"))
		if to_day and from_day <= day_no <= to_day:
			return flt(tier.get("daily_rate"))
	return 0.0


def calculate_tiered_charge(chargeable_days: int, tiers: list[dict[str, Any]]) -> float:
	if chargeable_days <= 0 or not tiers:
		return 0.0
	total = 0.0
	for day_no in range(1, chargeable_days + 1):
		total += daily_rate_for_day(day_no, tiers)
	return flt(total)
