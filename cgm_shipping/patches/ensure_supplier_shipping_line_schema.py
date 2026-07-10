"""Ensure Supplier child tables for shipping line free days and detention tiers exist."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	ensure_supplier_container_charge_fields,
)


def execute():
	ensure_supplier_container_charge_fields()
	frappe.clear_cache(doctype="Supplier")
	frappe.db.commit()
