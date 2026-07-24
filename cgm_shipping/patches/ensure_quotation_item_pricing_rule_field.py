"""Ensure Quotation Item can store the selected Item Pricing Rule."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _upsert_cf


def execute() -> None:
	_upsert_cf(
		"Quotation Item",
		{
			"fieldname": "custom_selected_item_pricing_rule",
			"label": "Selected Item Pricing Rule",
			"fieldtype": "Link",
			"options": "Item Pricing Rule",
			"insert_after": "item_code",
			"in_list_view": 1,
			"columns": 2,
			"description": "Pricing rule chosen for this line. Leave empty to use the highest calculated rule amount.",
		},
	)
	frappe.clear_cache(doctype="Quotation Item")
