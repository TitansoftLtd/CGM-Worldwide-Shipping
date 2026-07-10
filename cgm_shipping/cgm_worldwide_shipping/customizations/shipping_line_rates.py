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

SUPPLIER_CHILD_TABLE_FIELDS = (
	FREE_DAYS_RULES_FIELD,
	DEMURRAGE_TIERS_FIELD,
	DETENTION_TIERS_FIELD,
)


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
def get_valid_destinations() -> list[str]:
	"""Read destination names from Delivery Destination master."""
	if frappe.db.exists("DocType", "Delivery Destination"):
		return frappe.get_all("Delivery Destination", pluck="name", order_by="name asc")
	if frappe.db.table_exists("Delivery Destination"):
		return frappe.db.sql_list(
			"SELECT name FROM `tabDelivery Destination` ORDER BY name asc"
		)
	return []


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
	cargo_type: str | None, container_number: str | None = None
) -> str:
	label = (cargo_type or "").upper()
	if container_number and "RF" in container_number.upper():
		return _category_name("Reefer")
	if "REEFER" in label or label.endswith("RF") or " RF" in label:
		return _category_name("Reefer")
	return _category_name("Standard")


def resolve_cargo_type_key(cargo_type: str | None) -> str:
	valid_types = (
		frappe.get_all("Cargo Type", pluck="cargo_type", order_by="name asc")
		if frappe.db.exists("DocType", "Cargo Type")
		else []
	)
	if not cargo_type:
		return "All"
	label = cargo_type.upper()
	if "REEFER" in label or label.endswith("RF"):
		for size in valid_types:
			if size.upper() == "REEFER":
				return size
		return "All"
	for size in sorted(valid_types, key=len, reverse=True):
		key = size.upper()
		if key.replace("FT", "") in label.replace(" ", "") or key in label:
			return size
	if frappe.db.exists("Cargo Type", cargo_type):
		name = (
			frappe.db.get_value("Cargo Type", cargo_type, "cargo_type") or ""
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


def _rule_row_dict(rule: Any) -> dict[str, Any]:
	return rule if isinstance(rule, dict) else rule.as_dict()


def _category_matches(rule_category: str | None, category: str) -> bool:
	rule_cat = rule_category or "All"
	return rule_cat in (category, "All")


def _rule_delivery_destination(rule: dict[str, Any]) -> str | None:
	"""Read destination from rule row (supports legacy destination_region column)."""
	dest = rule.get("delivery_destination") or rule.get("destination_region")
	return (dest or "").strip() or None


def _normalize_rule_destination(value: str | None) -> str | None:
	label = (value or "").strip()
	if not label:
		return None
	for dest in get_valid_destinations():
		if dest.lower() == label.lower():
			return dest
	return label


def _match_rule(
	rules: list[Any],
	destination: str,
	category: str,
) -> dict[str, Any] | None:
	specific: list[tuple[int, dict[str, Any]]] = []
	fallback: list[tuple[int, dict[str, Any]]] = []

	for raw in rules:
		rule = _rule_row_dict(raw)
		if not _category_matches(rule.get("container_category"), category):
			continue

		score = 1 if rule.get("container_category") == category else 0

		if rule.get("applies_to_all_destinations"):
			fallback.append((score, rule))
			continue

		region = _normalize_rule_destination(_rule_delivery_destination(rule))
		dest = _normalize_rule_destination(destination)
		if region and dest and region == dest:
			specific.append((score + 2, rule))

	if specific:
		specific.sort(key=lambda item: item[0], reverse=True)
		return specific[0][1]

	if fallback:
		fallback.sort(key=lambda item: item[0], reverse=True)
		return fallback[0][1]

	return None


def get_free_days_rule(
	shipping_line: str,
	destination: str,
	category: str,
) -> dict[str, Any] | None:
	if not shipping_line:
		return None
	rules = get_supplier_child_rows(shipping_line, FREE_DAYS_RULES_FIELD)
	if not rules:
		return _legacy_supplier_rule(shipping_line)
	normalized = _normalize_rule_destination(destination) or default_destination_name()
	return _match_rule(rules, normalized, category)


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
		"applies_to_all_destinations": 1,
		"delivery_destination": None,
		"container_category": "All",
	}


def build_rate_source_label(
	shipping_line: str, destination: str, category: str, rule: dict[str, Any] | None
) -> str:
	if not rule:
		return shipping_line or ""
	if rule.get("applies_to_all_destinations"):
		region = "All Destinations"
	else:
		region = _rule_delivery_destination(rule) or destination
	free_days = rule.get("free_days")
	return f"{shipping_line} {region} {category} ({free_days}-day)"


def get_charge_tiers(
	shipping_line: str, charge_type: str, cargo_type_key: str
) -> list[dict[str, Any]]:
	if not shipping_line:
		return []
	field = DEMURRAGE_TIERS_FIELD if charge_type == "demurrage" else DETENTION_TIERS_FIELD
	rows = get_supplier_child_rows(shipping_line, field)
	if not rows and charge_type == "demurrage":
		return _legacy_flat_demurrage_tier(shipping_line, cargo_type_key)
	if not rows and charge_type == "detention":
		return _legacy_flat_detention_tier(shipping_line, cargo_type_key)
	matched = [
		_rule_row_dict(r)
		for r in rows
		if _rule_row_dict(r).get("cargo_type") in (cargo_type_key, "All")
	]
	if not matched:
		matched = [
			_rule_row_dict(r)
			for r in rows
			if _rule_row_dict(r).get("cargo_type") == "All"
		]
	return sorted(matched, key=lambda r: int(r.get("from_day") or 1))


def _legacy_flat_demurrage_tier(shipping_line: str, cargo_type_key: str) -> list[dict]:
	meta = frappe.get_meta("Supplier")
	if not meta.has_field("custom_demurrage_daily_rate"):
		return []
	rate = frappe.db.get_value("Supplier", shipping_line, "custom_demurrage_daily_rate")
	if not rate:
		return []
	return [
		{
			"cargo_type": cargo_type_key,
			"from_day": 1,
			"to_day": 0,
			"daily_rate": flt(rate),
		}
	]


def _legacy_flat_detention_tier(shipping_line: str, cargo_type_key: str) -> list[dict]:
	meta = frappe.get_meta("Supplier")
	if not meta.has_field("custom_detention_daily_rate"):
		return []
	rate = frappe.db.get_value("Supplier", shipping_line, "custom_detention_daily_rate")
	if not rate:
		return []
	return [
		{
			"cargo_type": cargo_type_key,
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
