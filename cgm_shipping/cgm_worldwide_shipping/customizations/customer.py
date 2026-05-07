import frappe


def fill_shipment_defaults_from_lead(doc, method=None):
	# Step 1: stop if customer has no source lead.
	if not doc.lead_name or not frappe.db.exists("Lead", doc.lead_name):
		return
	# Step 2: stop if shipment fields are unavailable.
	meta = frappe.get_meta("Customer")
	if not meta.has_field("custom_shipment_type"):
		return
	# Step 3: keep user-entered values unchanged.
	if doc.get("custom_shipment_type") and doc.get("custom_mode_of_transport"):
		return
	# Step 4: load shipment defaults from source lead.
	row = frappe.db.get_value(
		"Lead",
		doc.lead_name,
		["custom_shipment_type", "custom_mode_of_transport"],
		as_dict=True,
	)
	if not row:
		return
	# Step 5: copy values only when target is empty.
	if not doc.get("custom_shipment_type") and row.get("custom_shipment_type"):
		doc.custom_shipment_type = row.custom_shipment_type
	if meta.has_field("custom_mode_of_transport") and not doc.get("custom_mode_of_transport") and row.get(
		"custom_mode_of_transport"
	):
		doc.custom_mode_of_transport = row.custom_mode_of_transport
