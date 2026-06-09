import frappe

DOCTYPE = "Clearance Station Code"

# Custom Field -> fetch_from source (Clearance Station link field . station_code)
FIELD_CONVERSIONS = {
	"Opportunity-custom_station_code": "custom_clearance_station.station_code",
	"Project-custom_clearance_station_code": "custom_cfs.station_code",
}


def execute():
	"""Drop the Clearance Station Code master.

	The station code now lives as a Data field on Clearance Station, and the two
	link fields that pointed at this master become Data fields that fetch the code
	from the selected Clearance Station. Existing stored values (the old link
	names, which equalled the code) are preserved as plain Data.
	"""
	# 1. Convert the Link custom fields to Data. Custom Field.validate() refuses a
	#    Link -> Data change, so write the metadata directly.
	for cf_name, fetch_from in FIELD_CONVERSIONS.items():
		if not frappe.db.exists("Custom Field", cf_name):
			continue
		frappe.db.set_value(
			"Custom Field",
			cf_name,
			{
				"fieldtype": "Data",
				"options": "",
				"fetch_from": fetch_from,
				"read_only": 1,
			},
			update_modified=False,
		)

	frappe.clear_cache(doctype="Opportunity")
	frappe.clear_cache(doctype="Project")

	# 2. Drop the now-unused doctype (force past the link check and any records).
	if frappe.db.exists("DocType", DOCTYPE):
		frappe.delete_doc("DocType", DOCTYPE, force=True, ignore_missing=True)

	frappe.db.commit()
