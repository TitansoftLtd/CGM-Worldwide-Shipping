"""Shipping-line free days and demurrage tier lookup."""
from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

DEMURRAGE_TIERS_FIELD = "custom_shipping_line_demurrage_tiers"


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


@frappe.request_cache
def supplier_has_child_table_field(fieldname: str) -> bool:
	if not frappe.db.exists("DocType", "Supplier"):
		return False
	return frappe.get_meta("Supplier").has_field(fieldname)


@frappe.request_cache
def get_supplier_child_rows(supplier_name: str, fieldname: str) -> list:
	"""Safely read a Supplier child table; returns [] when the field is not on the DocType.

	Cached per request: rate lookups run once per container per charge type, and each
	miss was a full Supplier document load (all child tables) for the same few
	shipping lines. Treat the returned rows as read-only.
	"""
	if not supplier_name or not frappe.db.exists("Supplier", supplier_name):
		return []
	if not supplier_has_child_table_field(fieldname):
		return []
	child_doctype = (frappe.get_meta("Supplier").get_field(fieldname).options or "").strip()
	if not child_doctype:
		return []
	return (
		frappe.get_all(
			child_doctype,
			filters={"parent": supplier_name, "parenttype": "Supplier", "parentfield": fieldname},
			fields=["*"],
			order_by="idx asc",
		)
		or []
	)


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
