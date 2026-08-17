"""Install CGM Funding Request and Material Request funding workflows (idempotent)."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
	ensure_funding_request_setup,
)


def execute() -> None:
	ensure_funding_request_setup()
	frappe.db.commit()
