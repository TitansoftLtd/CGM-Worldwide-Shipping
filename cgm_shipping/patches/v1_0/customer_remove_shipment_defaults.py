import frappe


def execute():
	for cf_name in ("Customer-custom_shipment_type", "Customer-custom_mode_of_transport"):
		if frappe.db.exists("Custom Field", cf_name):
			frappe.delete_doc("Custom Field", cf_name, ignore_permissions=True, force=True)
	# Step 2: re-apply KRA PIN field position (was after removed mode field → use tax_id).
	from cgm_shipping.patches.v1_0.customer_kra_pin_field import execute as ensure_kra_pin_field

	ensure_kra_pin_field()

