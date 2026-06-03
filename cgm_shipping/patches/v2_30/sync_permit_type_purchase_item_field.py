"""Ensure Permit Type.purchase_item column exists (sites that ran v2_29 before schema sync)."""
from __future__ import annotations

import frappe


def execute():
	if frappe.db.exists("DocType", "Permit Type"):
		frappe.reload_doc("cgm_worldwide_shipping", "doctype", "permit_type")

	if not frappe.db.has_column("Permit Type", "purchase_item"):
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.permit_item_mapping import (
		seed_permit_type_purchase_items,
	)

	seed_permit_type_purchase_items()
	frappe.clear_cache(doctype="Permit Type")
