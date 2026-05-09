import frappe


def execute():
	add_if_missing(
		"Task",
		{
			"fieldname": "custom_payment_entry",
			"label": "Payment Entry",
			"fieldtype": "Link",
			"options": "Payment Entry",
			"insert_after": "custom_external_ref_no",
			"read_only": 1,
		},
	)


def add_if_missing(dt, spec):
	name = f"{dt}-{spec['fieldname']}"
	if frappe.db.exists("Custom Field", name):
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	for key, value in spec.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)
