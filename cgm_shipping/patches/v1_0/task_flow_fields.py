import frappe


def execute():
	add_if_missing(
		"Task",
		{
			"fieldname": "custom_task_flow_key",
			"label": "Task Flow Key",
			"fieldtype": "Data",
			"insert_after": "department",
			"read_only": 1,
			"hidden": 1,
		},
	)
	add_if_missing(
		"Task",
		{
			"fieldname": "custom_sequence_no",
			"label": "Sequence No",
			"fieldtype": "Int",
			"insert_after": "custom_task_flow_key",
			"read_only": 1,
			"hidden": 1,
		},
	)


def add_if_missing(dt, spec):
	name = f"{dt}-{spec['fieldname']}"
	if frappe.db.exists("Custom Field", name):
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	for k, v in spec.items():
		setattr(doc, k, v)
	doc.insert(ignore_permissions=True)
