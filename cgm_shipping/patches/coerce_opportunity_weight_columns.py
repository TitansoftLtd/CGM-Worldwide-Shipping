"""Re-clean Opportunity weight columns immediately before customization sync.

The pre_model_sync sanitizer can miss values when the DB driver returns
types the first pass does not normalize (e.g. Decimal edge cases, empty
strings on legacy varchar columns). Staging migrate failed at:

    ALTER TABLE `tabOpportunity`
    MODIFY `custom_weight_nw` decimal(21,9) NOT NULL DEFAULT 0.0

This patch runs in post_model_sync (after DocType sync, before
sync_customizations) and uses direct SQL updates so the ALTER succeeds.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_weight_sanitize import (
	sanitize_opportunity_weight_columns,
)


def execute() -> None:
	updated = sanitize_opportunity_weight_columns()
	if updated:
		frappe.logger("cgm_shipping").info(
			"coerce_opportunity_weight_columns: updated %s row(s)", updated
		)
	frappe.db.commit()
