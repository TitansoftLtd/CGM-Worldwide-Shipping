"""Sea import setup: roles + Project ETD/ETA fields and shipment-status option.

The workflow fixtures were removed, so this patch only seeds the CGM roles and
the Project fields. ``custom_shipment_status`` is now a plain status select.
"""

import frappe


def execute():
	ensure_roles()
	ensure_project_fields()


def ensure_roles():
	for role_name in ["Operations Manager", "CGM Documentation", "Declarant", "Finance Manager", "Field Officer", "Transport Manager"]:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)


def ensure_project_fields():
	# Step 1: create clear ETD/ETA fields if they don't exist yet.
	create_custom_field(
		"Project",
		{
			"fieldname": "custom_etd",
			"label": "Expected Time of Departure (ETD)",
			"fieldtype": "Date",
			"insert_after": "expected_start_date",
		},
	)
	create_custom_field(
		"Project",
		{
			"fieldname": "custom_eta",
			"label": "Expected Time of Arrival (ETA)",
			"fieldtype": "Date",
			"insert_after": "expected_end_date",
		},
	)

	# Step 2: ensure shipment status options include container return state.
	status_field_name = "Project-custom_shipment_status"
	if frappe.db.exists("Custom Field", status_field_name):
		status_field = frappe.get_doc("Custom Field", status_field_name)
		required_state = "Container Return Pending"
		current_options = (status_field.options or "").split("\n")
		if required_state not in current_options:
			current_options.append(required_state)
			status_field.options = "\n".join(opt for opt in current_options if opt)
			status_field.save(ignore_permissions=True)


def create_custom_field(dt, values):
	field_name = f"{dt}-{values['fieldname']}"
	if frappe.db.exists("Custom Field", field_name):
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	for key, value in values.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)
