import frappe


def execute():
	# Step 1: add CI/PKL attach fields to Lead for pre-shipment verification.
	add_attach_field(
		"Lead",
		{
			"fieldname": "custom_ci_attachment",
			"label": "CI Attachment",
			"fieldtype": "Attach",
			"insert_after": "custom_mode_of_transport",
		},
	)
	add_attach_field(
		"Lead",
		{
			"fieldname": "custom_pkl_attachment",
			"label": "PKL Attachment",
			"fieldtype": "Attach",
			"insert_after": "custom_ci_attachment",
		},
	)

	# Step 2: add CI/PKL attach fields to Opportunity for repeat-customer flow.
	add_attach_field(
		"Opportunity",
		{
			"fieldname": "custom_ci_attachment",
			"label": "CI Attachment",
			"fieldtype": "Attach",
			"insert_after": "custom_mode_of_transport",
		},
	)
	add_attach_field(
		"Opportunity",
		{
			"fieldname": "custom_pkl_attachment",
			"label": "PKL Attachment",
			"fieldtype": "Attach",
			"insert_after": "custom_ci_attachment",
		},
	)


def add_attach_field(dt, values):
	field_name = f"{dt}-{values['fieldname']}"
	if frappe.db.exists("Custom Field", field_name):
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	for key, value in values.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)

