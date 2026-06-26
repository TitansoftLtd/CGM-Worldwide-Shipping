"""Move container tracking settings from Custom Fields to CGM Shipping Settings doctype."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	ensure_container_tracking_settings_fields,
)


def execute() -> None:
	ensure_container_tracking_settings_fields()
	frappe.db.commit()
