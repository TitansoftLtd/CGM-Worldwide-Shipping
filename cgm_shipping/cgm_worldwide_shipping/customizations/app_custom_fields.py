"""Custom Fields only code creates - they are not in custom/*.json.

Created when missing and never updated afterwards: Customize Form owns them once
they exist. Everything else the app adds to standard DocTypes is exported to
custom/*.json and synced by migrate.
"""

from __future__ import annotations

import frappe

QUOTATION_ITEM_FIELDS = (
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

# Container charge accruals and deposit postings stamp their Journal Entries.
JOURNAL_ENTRY_FIELDS = (
	{
		"fieldname": "custom_cgm_source_project",
		"label": "CGM Source Project",
		"fieldtype": "Link",
		"options": "Project",
		"insert_after": "custom_cgm_source_task",
		"read_only": 1,
	},
	{
		"fieldname": "custom_cgm_accrual_kind",
		"label": "CGM Accrual Kind",
		"fieldtype": "Data",
		"insert_after": "custom_cgm_source_project",
		"read_only": 1,
	},
	{
		"fieldname": "custom_cgm_container_charge_lines",
		"label": "Container Charge Lines",
		"fieldtype": "Table",
		"options": "CGM Container Charge Accrual Line",
		"insert_after": "custom_cgm_accrual_kind",
		"read_only": 1,
	},
	{
		"fieldname": "custom_cgm_source_container_tracker",
		"label": "CGM Source Container Tracker",
		"fieldtype": "Link",
		"options": "Container Tracker",
		"insert_after": "custom_cgm_source_task",
		"read_only": 1,
	},
	{
		"fieldname": "custom_cgm_source_bill_of_lading",
		"label": "CGM Source Bill of Lading",
		"fieldtype": "Link",
		"options": "Bill of Lading",
		"insert_after": "custom_cgm_source_container_tracker",
		"read_only": 1,
	},
	{
		"fieldname": "custom_cgm_deposit_entry_kind",
		"label": "CGM Deposit Entry Kind",
		"fieldtype": "Select",
		"options": "\nOutbound\nRefund",
		"insert_after": "custom_cgm_source_bill_of_lading",
		"read_only": 1,
	},
)

CONTAINER_TRACKER_FIELDS = (
	{
		"fieldname": "section_container_charges",
		"label": "Accrued Charges",
		"fieldtype": "Section Break",
		"insert_after": "kpa_days",
		"collapsible": 0,
	},
	{
		"fieldname": "demurrage_daily_rate",
		"label": "Demurrage/Detention Daily Rate",
		"fieldtype": "Currency",
		"insert_after": "section_container_charges",
		"description": "From shipping line tiers or flat rate. Edit to override calculated amount.",
	},
	{
		"fieldname": "demurrage_rate_currency",
		"label": "Demurrage Currency",
		"fieldtype": "Link",
		"options": "Currency",
		"insert_after": "demurrage_daily_rate",
	},
	{
		"fieldname": "demurrage_amount",
		"label": "Demurrage/Detention Amount Accrued",
		"fieldtype": "Currency",
		"insert_after": "demurrage_rate_currency",
		"read_only": 1,
		"bold": 1,
	},
	{
		"fieldname": "demurrage_amount_adjustment",
		"label": "Demurrage Adjustment",
		"fieldtype": "Currency",
		"insert_after": "demurrage_amount",
		"description": "Added to the calculated demurrage total when the rate table is slightly off.",
	},
	{
		"fieldname": "column_break_container_charges",
		"fieldtype": "Column Break",
		"insert_after": "demurrage_amount_adjustment",
	},
	{
		"fieldname": "kpa_port_daily_rate",
		"label": "KPA Port Daily Rate",
		"fieldtype": "Currency",
		"insert_after": "column_break_container_charges",
		"description": "From CGM Settings. Edit to override on this container.",
	},
	{
		"fieldname": "kpa_rate_currency",
		"label": "KPA Port Currency",
		"fieldtype": "Link",
		"options": "Currency",
		"insert_after": "kpa_port_daily_rate",
	},
	{
		"fieldname": "kpa_amount",
		"label": "KPA Port Amount Accrued",
		"fieldtype": "Currency",
		"insert_after": "kpa_rate_currency",
		"read_only": 1,
		"bold": 1,
	},
	{
		"fieldname": "kpa_amount_adjustment",
		"label": "KPA Port Adjustment",
		"fieldtype": "Currency",
		"insert_after": "kpa_amount",
	},
	{
		"fieldname": "section_container_charges_posted",
		"label": "Posted to Journal",
		"fieldtype": "Section Break",
		"insert_after": "kpa_amount_adjustment",
		"collapsible": 1,
	},
	{
		"fieldname": "demurrage_amount_posted_to_je",
		"label": "Demurrage Posted to JE",
		"fieldtype": "Currency",
		"insert_after": "section_container_charges_posted",
		"read_only": 1,
	},
	{
		"fieldname": "kpa_amount_posted_to_je",
		"label": "KPA Port Posted to JE",
		"fieldtype": "Currency",
		"insert_after": "demurrage_amount_posted_to_je",
		"read_only": 1,
	},
)


def ensure_app_custom_fields() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _create_cf

	for doctype, fields in (
		("Quotation Item", QUOTATION_ITEM_FIELDS),
		("Journal Entry", JOURNAL_ENTRY_FIELDS),
		("Container Tracker", CONTAINER_TRACKER_FIELDS),
	):
		if not frappe.db.exists("DocType", doctype):
			continue
		for values in fields:
			_create_cf(doctype, dict(values))
		frappe.clear_cache(doctype=doctype)
	frappe.db.commit()
