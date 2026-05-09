import frappe


def execute():
	# Step 1: add a task-level document child table for seamless uploads.
	add_if_missing(
		"Task",
		{
			"fieldname": "custom_task_documents",
			"label": "Task Documents",
			"fieldtype": "Table",
			"options": "Shipment Document",
			"insert_after": "custom_payment_entry",
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
