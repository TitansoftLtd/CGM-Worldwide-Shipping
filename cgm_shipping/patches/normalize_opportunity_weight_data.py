"""Normalize surviving Opportunity weight columns before the decimal schema sync.

``custom_gross_weight`` / ``custom_net_weight`` are Float fields (in
``custom/opportunity.json``) whose columns still hold unsanitized legacy data
(empty strings / non-numeric text on the old varchar column). ``sync_customizations``
runs ``ALTER TABLE ... MODIFY <col> decimal(21,9) NOT NULL`` which fails with
MySQL 1265 ("Data truncated") on those values.

This patch coerces every row to a valid decimal(21,9) so the ALTER succeeds.
Runs in pre_model_sync, before ``sync_customizations``. Opportunity only.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import frappe

DOCTYPE = "Opportunity"
WEIGHT_FIELDS = ("custom_gross_weight", "custom_net_weight")

_MAX = Decimal("999999999999.999999999")
_MIN = -_MAX
_QUANT = Decimal("0.000000001")
_ZERO = Decimal("0")


def _safe_decimal(raw) -> Decimal:
	"""Coerce any stored value into a decimal(21,9)-safe Decimal (0 when invalid)."""
	if raw is None:
		return _ZERO
	if isinstance(raw, Decimal):
		value = raw
	elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
		try:
			value = Decimal(str(raw))
		except (InvalidOperation, ValueError):
			return _ZERO
	else:
		text = str(raw).strip().replace(",", "")
		if not text:
			return _ZERO
		try:
			value = Decimal(text)
		except (InvalidOperation, ValueError):
			return _ZERO
	if value.is_nan() or value.is_infinite():
		return _ZERO
	# Clamp before quantize — quantizing an out-of-range value overflows the
	# default decimal context precision and raises InvalidOperation.
	if value > _MAX:
		return _MAX
	if value < _MIN:
		return _MIN
	try:
		return value.quantize(_QUANT)
	except InvalidOperation:
		return _ZERO


def execute() -> None:
	if not frappe.db.table_exists(DOCTYPE):
		return

	for fieldname in WEIGHT_FIELDS:
		if not frappe.db.has_column(DOCTYPE, fieldname):
			continue
		rows = frappe.db.sql(
			f"SELECT name, `{fieldname}` AS value FROM `tab{DOCTYPE}`", as_dict=True
		)
		for row in rows:
			frappe.db.sql(
				f"UPDATE `tab{DOCTYPE}` SET `{fieldname}` = %s WHERE name = %s",
				(_safe_decimal(row.value), row.name),
			)

	frappe.db.commit()
