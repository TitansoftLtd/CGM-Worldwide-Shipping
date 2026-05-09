import frappe


def execute():
	# Step 1: Ensure Customer has mandatory KRA PIN proof upload for clearance onboarding.
	spec = {
		"fieldname": "custom_kra_pin_attachment",
		"label": "KRA PIN Document",
		"fieldtype": "Attach",
		# Main profile strip (basic_info … image), before Defaults tab — avoid Tax tab / Connections lumping.
		"insert_after": "image",
		"reqd": 1,
		"description": "Upload official KRA PIN certificate or clearance letter for this importer. Required for Kenyan import operations.",
	}
	cf_name = f"Customer-{spec['fieldname']}"
	if frappe.db.exists("Custom Field", cf_name):
		doc = frappe.get_doc("Custom Field", cf_name)
		doc.fieldtype = "Attach"
		doc.label = spec["label"]
		doc.reqd = 1
		doc.description = spec["description"]
		doc.insert_after = spec["insert_after"]
		doc.save(ignore_permissions=True)
		return

	doc = frappe.new_doc("Custom Field")
	doc.dt = "Customer"
	for key, value in spec.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)
