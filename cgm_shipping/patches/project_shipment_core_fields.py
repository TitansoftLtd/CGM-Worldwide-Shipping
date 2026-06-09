"""Add full shipment core fields on Project (transport, ops, charges, documents)."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	ensure_project_shipment_core_fields,
)


def execute():
	ensure_project_shipment_core_fields()
	frappe.db.commit()
