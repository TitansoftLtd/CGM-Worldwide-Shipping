"""Custom Fields only code creates - they are not in custom/*.json.

Created when missing and never updated afterwards: Customize Form owns them once
they exist. Everything else the app adds to standard DocTypes is exported to
custom/*.json and synced by migrate.

Fields production has since deleted (the container charge fields, the Journal
Entry accrual fields, Quotation Item's selected pricing rule) are deliberately
not here, so migrate does not bring them back.
"""

from __future__ import annotations

import frappe

# Container deposit postings stamp their Journal Entries.
JOURNAL_ENTRY_FIELDS = (
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


def ensure_app_custom_fields() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _create_cf

	if not frappe.db.exists("DocType", "Journal Entry"):
		return
	for values in JOURNAL_ENTRY_FIELDS:
		_create_cf("Journal Entry", dict(values))
	frappe.clear_cache(doctype="Journal Entry")
	frappe.db.commit()
