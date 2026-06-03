"""Link Permit Type master to purchase Items (Dvs Permit, Kebs Permit, etc.)."""
from __future__ import annotations

import frappe


def execute():
	if frappe.db.exists("DocType", "Permit Type"):
		frappe.reload_doc("cgm_worldwide_shipping", "doctype", "permit_type")

	from cgm_shipping.cgm_worldwide_shipping.customizations.permit_item_mapping import (
		seed_permit_type_purchase_items,
	)

	seed_permit_type_purchase_items()
	frappe.clear_cache(doctype="Permit Type")
