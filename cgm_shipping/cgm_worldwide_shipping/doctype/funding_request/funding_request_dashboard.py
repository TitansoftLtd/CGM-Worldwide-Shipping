# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from frappe import _


def get_data():
	return {
		"fieldname": "custom_funding_request",
		"non_standard_fieldnames": {
			"Material Request": "custom_funding_request",
			"Employee Advance": "custom_funding_request",
			"Purchase Order": "custom_funding_request",
			"Payment Entry": "project",
		},
		"internal_links": {
			"Material Request": ["material_requests", "material_request"],
		},
		"transactions": [
			{"label": _("Requests"), "items": ["Material Request"]},
			{"label": _("Employee Advance"), "items": ["Employee Advance"]},
			{"label": _("Purchase Order"), "items": ["Purchase Order"]},
		],
	}
