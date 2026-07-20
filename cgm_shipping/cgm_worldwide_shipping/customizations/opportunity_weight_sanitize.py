"""Shared helpers to normalize Opportunity weight columns before decimal ALTER."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe

OPPORTUNITY_WEIGHT_FIELDS = (
	"custom_weight_nw",
	"custom_gross_weight",
	"custom_net_weight",
)

# Frappe Float/Currency columns sync as decimal(21,9).
_MAX_WEIGHT = Decimal("999999999999.999999999")
_MIN_WEIGHT = Decimal("-999999999999.999999999")
_ZERO = Decimal("0")


def _coerce_weight_for_decimal(raw) -> float | None:
	"""Return a finite float or None when the stored value cannot be coerced."""
	if raw is None:
		return None
	if isinstance(raw, Decimal):
		try:
			if raw.is_nan() or raw.is_infinite():
				return None
			return float(raw)
		except (InvalidOperation, ValueError, OverflowError):
			return None
	if isinstance(raw, (int, float)) and not isinstance(raw, bool):
		value = float(raw)
		if value != value or value in (float("inf"), float("-inf")):
			return None
		return value
	text = str(raw).strip()
	if not text:
		return None
	try:
		return float(text.replace(",", ""))
	except (TypeError, ValueError, OverflowError):
		return None


def _safe_decimal_value(raw) -> Decimal:
	coerced = _coerce_weight_for_decimal(raw)
	if coerced is None:
		return _ZERO
	try:
		value = Decimal(str(coerced))
	except (InvalidOperation, ValueError, OverflowError):
		return _ZERO
	if value.is_nan() or value.is_infinite():
		return _ZERO
	value = value.quantize(Decimal("0.000000001"), rounding=ROUND_HALF_UP)
	if value > _MAX_WEIGHT:
		return _MAX_WEIGHT
	if value < _MIN_WEIGHT:
		return _MIN_WEIGHT
	return value


def _stored_as_safe_decimal(raw, safe: Decimal) -> bool:
	"""True only when the DB value can survive a decimal(21,9) NOT NULL column."""
	if raw is None:
		return safe == _ZERO
	if isinstance(raw, Decimal):
		try:
			return (
				not raw.is_nan()
				and not raw.is_infinite()
				and raw.quantize(Decimal("0.000000001"), rounding=ROUND_HALF_UP) == safe
			)
		except (InvalidOperation, ValueError, OverflowError):
			return False
	if isinstance(raw, (int, float)) and not isinstance(raw, bool):
		return _safe_decimal_value(raw) == safe
	text = str(raw).strip()
	if not text:
		return False
	if _coerce_weight_for_decimal(text) is None:
		return False
	return _safe_decimal_value(text) == safe


def sanitize_opportunity_weight_columns() -> int:
	"""Force-clean weight columns so decimal NOT NULL ALTER succeeds. Returns rows updated."""
	if not frappe.db.table_exists("Opportunity"):
		return 0

	updated = 0
	for fieldname in OPPORTUNITY_WEIGHT_FIELDS:
		if not frappe.db.has_column("Opportunity", fieldname):
			continue

		rows = frappe.db.sql(
			f"""
			SELECT name, `{fieldname}` AS value
			FROM `tabOpportunity`
			""",
			as_dict=True,
		)

		for row in rows:
			safe = _safe_decimal_value(row.value)
			if _stored_as_safe_decimal(row.value, safe):
				continue
			frappe.db.sql(
				f"""
				UPDATE `tabOpportunity`
				SET `{fieldname}` = %s
				WHERE name = %s
				""",
				(safe, row.name),
			)
			updated += 1

	if updated:
		frappe.clear_cache(doctype="Opportunity")
	return updated
