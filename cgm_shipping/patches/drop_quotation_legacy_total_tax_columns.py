"""Drop orphaned Quotation columns from legacy total-tax custom fields."""

import frappe

LEGACY_FIELDS = ("custom_total_taxes_kes", "custom_total_taxes_usd")


def execute():
	for fieldname in LEGACY_FIELDS:
		if frappe.db.has_column("Quotation", fieldname):
			frappe.db.sql_ddl(
				f"ALTER TABLE `tabQuotation` DROP COLUMN `{fieldname}`"
			)

		if frappe.db.exists("Custom Field", f"Quotation-{fieldname}"):
			frappe.delete_doc("Custom Field", f"Quotation-{fieldname}", force=1)

	frappe.clear_cache(doctype="Quotation")
