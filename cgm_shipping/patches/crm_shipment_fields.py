import frappe


def execute():
	add_if_missing(
		"Lead",
		{
			"fieldname": "custom_shipment_type",
			"label": "Shipment Type",
			"fieldtype": "Select",
			"options": "\nImport\nExport",
			"insert_after": insert_after_lead(),
		},
	)
	add_if_missing(
		"Lead",
		{
			"fieldname": "custom_mode_of_transport",
			"label": "Mode of Transport",
			"fieldtype": "Select",
			"options": "\nSea\nAir\nRoad",
			"insert_after": "custom_shipment_type",
		},
	)
	add_if_missing(
		"Opportunity",
		{
			"fieldname": "custom_shipment_type",
			"label": "Shipment Type",
			"fieldtype": "Link",
			"options": "Shipment Type",
			"insert_after": insert_after_opportunity(),
		},
	)
	add_if_missing(
		"Opportunity",
		{
			"fieldname": "custom_mode_of_transport",
			"label": "Mode of Transport",
			"fieldtype": "Link",
			"options": "Mode of Transport",
			"insert_after": "custom_shipment_type",
		},
	)
	add_if_missing(
		"Project",
		{
			"fieldname": "custom_source_lead",
			"label": "Source Lead",
			"fieldtype": "Link",
			"options": "Lead",
			"insert_after": "customer",
			"read_only": 1,
		},
	)
	add_if_missing(
		"Project",
		{
			"fieldname": "custom_source_opportunity",
			"label": "Source Opportunity",
			"fieldtype": "Link",
			"options": "Opportunity",
			"insert_after": "custom_source_lead",
			"read_only": 1,
		},
	)


def insert_after_lead():
	if frappe.db.exists("Custom Field", "Lead-custom_cgm_preshipment_status"):
		return "custom_cgm_preshipment_status"
	return "status"


def insert_after_opportunity():
	if frappe.db.exists("Custom Field", "Opportunity-custom_cgm_preshipment_status"):
		return "custom_cgm_preshipment_status"
	return "status"


def add_if_missing(dt, spec):
	name = f"{dt}-{spec['fieldname']}"
	if frappe.db.exists("Custom Field", name):
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	for k, v in spec.items():
		setattr(doc, k, v)
	doc.insert(ignore_permissions=True)
