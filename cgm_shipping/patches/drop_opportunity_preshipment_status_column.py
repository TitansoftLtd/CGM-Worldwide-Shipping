"""Drop the orphaned `custom_cgm_preshipment_status` column from Opportunity.
"""

import frappe


def execute():
	if frappe.db.has_column("Opportunity", "custom_cgm_preshipment_status"):
		frappe.db.sql_ddl(
			"ALTER TABLE `tabOpportunity` DROP COLUMN `custom_cgm_preshipment_status`"
		)
		frappe.clear_cache(doctype="Opportunity")
