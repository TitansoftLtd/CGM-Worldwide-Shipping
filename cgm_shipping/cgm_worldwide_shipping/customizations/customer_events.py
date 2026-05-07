import frappe


def fill_shipment_defaults_from_lead(doc, method=None):
	"""When Customer is tied to a Lead, copy Import/Sea etc. once if Customer fields are empty."""
	if not doc.lead_name or not frappe.db.exists("Lead", doc.lead_name):
		return
	meta = frappe.get_meta("Customer")
	if not meta.has_field("custom_shipment_type"):
		return
	if doc.get("custom_shipment_type") and doc.get("custom_mode_of_transport"):
		return
	row = frappe.db.get_value(
		"Lead",
		doc.lead_name,
		["custom_shipment_type", "custom_mode_of_transport"],
		as_dict=True,
	)
	if not row:
		return
	if not doc.get("custom_shipment_type") and row.get("custom_shipment_type"):
		doc.custom_shipment_type = row.custom_shipment_type
	if meta.has_field("custom_mode_of_transport") and not doc.get("custom_mode_of_transport") and row.get(
		"custom_mode_of_transport"
	):
		doc.custom_mode_of_transport = row.custom_mode_of_transport
