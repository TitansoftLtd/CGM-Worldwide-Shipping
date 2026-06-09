import frappe

CUSTOM_FIELD = "Opportunity-custom_shipment_type"


def execute():
	"""Convert Opportunity 'Shipment Type' from Select to a Link.

	Existing values (e.g. "Sea FCL", "Air Import", "Export") match the Shipment
	Type master names seeded by bootstrap_shipment_types, so they resolve as
	valid links. The legacy "Road Import" option has no exact master (the master
	is "Cross-Border Road Import") and is left untouched for manual review.
	"""
	if not frappe.db.exists("Custom Field", CUSTOM_FIELD):
		return
	current = frappe.db.get_value(
		"Custom Field", CUSTOM_FIELD, ["fieldtype", "options"], as_dict=True
	)
	if current.fieldtype == "Link" and current.options == "Shipment Type":
		return
	# Custom Field.validate() refuses a Select -> Link change, but the underlying
	# Opportunity column is varchar either way, so update the metadata directly.
	frappe.db.set_value(
		"Custom Field",
		CUSTOM_FIELD,
		{"fieldtype": "Link", "options": "Shipment Type"},
		update_modified=False,
	)
	frappe.clear_cache(doctype="Opportunity")
	frappe.db.commit()
