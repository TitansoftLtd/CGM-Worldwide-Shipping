"""Tailor the Opportunity form "Connections" for the shipping workflow.

ERPNext ships Quotation / Request for Quotation / Supplier Quotation. For CGM
the Opportunity branches into a Bill of Lading and a (shipment) Project, so we
keep Quotation, drop the two procurement quotations, and surface those two
shipping links instead.
"""


def get_dashboard_data(data):
	data["transactions"] = [
		{"label": "Quotation", "items": ["Quotation"]},
		{"label": "Shipment", "items": ["Bill of Lading", "Air Waybill"]},
		{"label": "Project", "items": ["Project"]},
	]
	non_standard = data.setdefault("non_standard_fieldnames", {})
	non_standard["Bill of Lading"] = "linked_opportunity"
	non_standard["Air Waybill"] = "linked_opportunity"
	non_standard["Project"] = "custom_source_opportunity"

	return data
