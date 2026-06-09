import frappe

CUSTOM_FIELD = "Opportunity-custom_mode_of_transport"


def execute():
	if not frappe.db.exists("Custom Field", CUSTOM_FIELD):
		return
	current = frappe.db.get_value(
		"Custom Field", CUSTOM_FIELD, ["fieldtype", "options"], as_dict=True
	)
	if current.fieldtype == "Link" and current.options == "Mode of Transport":
		return
	# Custom Field.validate() refuses a Select -> Link change, but the underlying
	# Opportunity column is varchar either way, so update the metadata directly.
	frappe.db.set_value(
		"Custom Field",
		CUSTOM_FIELD,
		{"fieldtype": "Link", "options": "Mode of Transport"},
		update_modified=False,
	)
	frappe.clear_cache(doctype="Opportunity")
	frappe.db.commit()
