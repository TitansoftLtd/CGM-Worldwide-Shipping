import frappe


def execute():
	add_if_missing(
		"Task",
		{
			"fieldname": "custom_purchase_invoice",
			"label": "Purchase Invoice",
			"fieldtype": "Link",
			"options": "Purchase Invoice",
			"insert_after": "custom_external_ref_no",
		},
	)
	# Keep Payment Entry after Purchase Invoice in the form.
	pe_name = frappe.db.get_value(
		"Custom Field", {"dt": "Task", "fieldname": "custom_payment_entry"}, "name"
	)
	if pe_name:
		frappe.db.set_value("Custom Field", pe_name, "insert_after", "custom_purchase_invoice")


def add_if_missing(dt, spec):
	name = f"{dt}-{spec['fieldname']}"
	if frappe.db.exists("Custom Field", name):
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	for key, value in spec.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)
