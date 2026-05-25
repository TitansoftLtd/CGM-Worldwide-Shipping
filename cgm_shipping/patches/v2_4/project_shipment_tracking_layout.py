"""Restructure Project top section: LCL tracking sheet fields + workflow chart area."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_tracking_layout import (
	ensure_project_tracking_layout,
)


def execute():
	ensure_project_tracking_layout()
	frappe.db.commit()
