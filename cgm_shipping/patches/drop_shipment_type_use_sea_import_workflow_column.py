"""Drop orphaned use_sea_import_workflow column from Shipment Type."""

import frappe


def execute():
	if frappe.db.has_column("Shipment Type", "use_sea_import_workflow"):
		frappe.db.sql_ddl(
			"ALTER TABLE `tabShipment Type` DROP COLUMN `use_sea_import_workflow`"
		)
		frappe.clear_cache(doctype="Shipment Type")
