"""Clean invalid Opportunity weight values before decimal schema sync.

During migrate, sync_customizations can ALTER weight fields to
``decimal NOT NULL DEFAULT 0``. Empty strings or non-numeric text raise
MySQL 1265 (Data truncated).
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_weight_sanitize import (
	sanitize_opportunity_weight_columns,
)


def execute() -> None:
	sanitize_opportunity_weight_columns()
	frappe.db.commit()
