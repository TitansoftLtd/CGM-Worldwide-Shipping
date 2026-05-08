import frappe


def execute():
	# Step 1: keep completion audit fields visible but read-only.
	upsert_property_setter("Task", "completed_by", "hidden", "0", "Check")
	upsert_property_setter("Task", "completed_on", "hidden", "0", "Check")
	upsert_property_setter("Task", "completed_by", "read_only", "1", "Check")
	upsert_property_setter("Task", "completed_on", "read_only", "1", "Check")
	# Step 2: make status read-only; completion is done through custom button.
	upsert_property_setter("Task", "status", "read_only", "1", "Check")


def upsert_property_setter(doc_type, field_name, prop, value, prop_type):
	ps_name = f"{doc_type}-{field_name}-{prop}"
	if frappe.db.exists("Property Setter", ps_name):
		ps = frappe.get_doc("Property Setter", ps_name)
		ps.value = value
		ps.save(ignore_permissions=True)
		return

	ps = frappe.get_doc(
		{
			"doctype": "Property Setter",
			"name": ps_name,
			"doc_type": doc_type,
			"doctype_or_field": "DocField",
			"field_name": field_name,
			"property": prop,
			"property_type": prop_type,
			"value": value,
		}
	)
	ps.insert(ignore_permissions=True)
