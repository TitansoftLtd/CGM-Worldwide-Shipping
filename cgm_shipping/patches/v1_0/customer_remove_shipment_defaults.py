import frappe


def execute():
	for cf_name in ("Customer-custom_shipment_type", "Customer-custom_mode_of_transport"):
		if frappe.db.exists("Custom Field", cf_name):
			frappe.delete_doc("Custom Field", cf_name, ignore_permissions=True, force=True)
	_ensure_customer_kra_pin_field()


def _ensure_customer_kra_pin_field():
	"""Re-apply KRA PIN on Customer after removing mode/shipment fields (insert after tax_id)."""
	spec = {
		"fieldname": "custom_kra_pin_attachment",
		"label": "KRA PIN Document",
		"fieldtype": "Attach",
		"insert_after": "tax_id",
		"reqd": 1,
		"description": (
			"Upload official KRA PIN certificate or clearance letter for this importer. "
			"Required for Kenyan import operations."
		),
	}
	cf_name = f"Customer-{spec['fieldname']}"
	if frappe.db.exists("Custom Field", cf_name):
		doc = frappe.get_doc("Custom Field", cf_name)
		doc.fieldtype = spec["fieldtype"]
		doc.label = spec["label"]
		doc.reqd = spec["reqd"]
		doc.description = spec["description"]
		doc.insert_after = spec["insert_after"]
		doc.save(ignore_permissions=True)
		return

	doc = frappe.new_doc("Custom Field")
	doc.dt = "Customer"
	for key, value in spec.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)
