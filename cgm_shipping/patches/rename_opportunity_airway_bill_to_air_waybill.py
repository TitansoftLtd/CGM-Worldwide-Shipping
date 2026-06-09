"""Make `custom_air_waybill` the canonical Opportunity → Air Waybill field.

The visible AWB link is now `custom_air_waybill` (matching the Air Waybill doctype
name); the older `custom_airway_bill` is retired. This migrates any data across and
removes the old field, handling both migrate orderings (whether customization sync
created the new field before this patch runs or not).
"""

import frappe


def execute():
	if not frappe.db.has_column("Opportunity", "custom_airway_bill"):
		return

	if frappe.db.has_column("Opportunity", "custom_air_waybill"):
		# New field already exists (created by customization sync): copy data over.
		frappe.db.sql(
			"""
			UPDATE `tabOpportunity`
			SET custom_air_waybill = custom_airway_bill
			WHERE IFNULL(custom_air_waybill, '') = '' AND IFNULL(custom_airway_bill, '') != ''
			"""
		)
		if frappe.db.exists("Custom Field", "Opportunity-custom_airway_bill"):
			frappe.delete_doc(
				"Custom Field", "Opportunity-custom_airway_bill", ignore_permissions=True
			)
	else:
		# Only the old field exists: rename in place (preserves data + Custom Field).
		from frappe.model.utils.rename_field import rename_field

		rename_field("Opportunity", "custom_airway_bill", "custom_air_waybill")

	frappe.db.commit()
	frappe.clear_cache(doctype="Opportunity")
