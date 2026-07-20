"""Ensure Supplier.custom_is_shipping_line exists and charge fields depend on it."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	ensure_supplier_container_charge_fields,
)


def execute() -> None:
	ensure_supplier_container_charge_fields()
	frappe.clear_cache(doctype="Supplier")
	frappe.db.commit()
