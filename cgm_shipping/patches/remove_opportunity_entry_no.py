"""Remove orphan Entry No from Opportunity.

Deleting a custom field on production and exporting customizations updates
``custom/opportunity.json`` but does not remove the Custom Field row (or DB
column) on other sites. Migrate only syncs fields present in JSON.
"""

import frappe

FIELDNAME = "custom_entry_no"
CF_NAME = f"Opportunity-{FIELDNAME}"


def execute():
	if frappe.db.exists("Custom Field", CF_NAME):
		frappe.delete_doc("Custom Field", CF_NAME, force=1, ignore_permissions=True)

	for name in frappe.get_all(
		"Property Setter",
		filters={"doc_type": "Opportunity", "field_name": FIELDNAME},
		pluck="name",
	):
		frappe.delete_doc("Property Setter", name, force=1, ignore_permissions=True)

	if frappe.db.has_column("Opportunity", FIELDNAME):
		frappe.db.sql_ddl(f"ALTER TABLE `tabOpportunity` DROP COLUMN `{FIELDNAME}`")

	frappe.clear_cache(doctype="Opportunity")
