"""Drop unused Finance Cost Category Map settings and child doctype data."""
from __future__ import annotations

import frappe

SETTINGS = "CGM Shipping Settings"
CHILD_DOCTYPE = "Finance Cost Category Map"
REMOVED_FIELDS = (
	"custom_finance_cost_category_map",
	"section_finance_cost_category_map",
	"tab_finance_cost_ledger",
)


def execute() -> None:
	if frappe.db.table_exists(f"tab{CHILD_DOCTYPE}"):
		frappe.db.delete(
			CHILD_DOCTYPE,
			{"parent": SETTINGS, "parenttype": SETTINGS},
		)

	if frappe.db.exists("DocType", SETTINGS):
		for fieldname in REMOVED_FIELDS:
			frappe.db.delete(
				"DocField",
				{"parent": SETTINGS, "parenttype": "DocType", "fieldname": fieldname},
			)

	frappe.clear_cache(doctype=SETTINGS)
	frappe.db.commit()
