"""Clean invalid Opportunity weight values before decimal schema sync.

During migrate, sync_customizations can ALTER ``custom_gross_weight`` and
``custom_weight_nw`` to ``decimal NOT NULL DEFAULT 0``. Empty strings or
non-numeric text in existing rows raise MySQL 1265 (Data truncated).

This patch runs before customizations sync and normalizes bad values to ``0``
so the ALTER succeeds without losing valid numeric weights.
"""

from __future__ import annotations

import frappe

OPPORTUNITY_WEIGHT_FIELDS = (
	"custom_weight_nw",
	"custom_gross_weight",
	"custom_net_weight",
)


def _coerce_weight_for_decimal(raw) -> float | None:
	"""Return a finite float or None when the stored value cannot be coerced."""
	if raw is None:
		return None
	if isinstance(raw, (int, float)) and not isinstance(raw, bool):
		return float(raw)
	text = str(raw).strip()
	if not text:
		return None
	try:
		return float(text.replace(",", ""))
	except (TypeError, ValueError):
		return None


def execute() -> None:
	if not frappe.db.table_exists("Opportunity"):
		return

	for fieldname in OPPORTUNITY_WEIGHT_FIELDS:
		if not frappe.db.has_column("Opportunity", fieldname):
			continue

		rows = frappe.db.sql(
			f"""
			SELECT name, `{fieldname}` AS value
			FROM `tabOpportunity`
			WHERE `{fieldname}` IS NOT NULL
			""",
			as_dict=True,
		)

		for row in rows:
			raw = row.value
			coerced = _coerce_weight_for_decimal(raw)
			new_value = coerced if coerced is not None else 0

			# Skip rows that already store a clean numeric value.
			if isinstance(raw, (int, float)) and not isinstance(raw, bool):
				if float(raw) == new_value:
					continue
			elif coerced is not None and str(raw).replace(",", "").strip() == str(coerced):
				continue
			elif raw in (0, 0.0, "0", "0.0") and new_value == 0:
				continue

			frappe.db.set_value(
				"Opportunity",
				row.name,
				fieldname,
				new_value,
				update_modified=False,
			)

	frappe.db.commit()
	frappe.clear_cache(doctype="Opportunity")
