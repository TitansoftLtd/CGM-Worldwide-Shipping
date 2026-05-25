"""Default purchase item for permit PI line pre-fill."""
import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_shipment_fields import (
		_create_cf,
	)

	_create_cf(
		"CGM Shipping Settings",
		{
			"fieldname": "custom_section_finance_defaults",
			"fieldtype": "Section Break",
			"label": "Finance Defaults",
			"insert_after": "section_break_sea_import",
			"collapsible": 1,
		},
	)
	_create_cf(
		"CGM Shipping Settings",
		{
			"fieldname": "custom_default_purchase_item",
			"label": "Default Purchase Item (Permits / Clearance)",
			"fieldtype": "Link",
			"options": "Item",
			"insert_after": "custom_section_finance_defaults",
			"description": "Used when Finance creates a Purchase Invoice from permit payment tasks.",
		},
	)

	if not frappe.db.exists("Item", "CGM-CLEARANCE-CHARGE"):
		item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
		item = frappe.new_doc("Item")
		item.item_code = "CGM-CLEARANCE-CHARGE"
		item.item_name = "Import Clearance / Permit Charge"
		item.item_group = item_group
		item.is_stock_item = 0
		item.is_purchase_item = 1
		item.standard_rate = 0
		item.insert(ignore_permissions=True)

	frappe.clear_cache()
