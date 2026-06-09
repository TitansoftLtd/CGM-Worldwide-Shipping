"""Bill of Lading + container picker fields on Container Tracker."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	_create_cf,
)

BL_DEPENDS = "eval:doc.custom_bill_of_lading"


def execute():
	_create_cf(
		"Container Tracker",
		{
			"fieldname": "custom_section_bl_tracking",
			"label": "B/L & Container",
			"fieldtype": "Section Break",
			"insert_after": "project",
			"collapsible": 0,
		},
	)
	_create_cf(
		"Container Tracker",
		{
			"fieldname": "custom_bill_of_lading",
			"label": "Bill of Lading",
			"fieldtype": "Link",
			"options": "Bill of Lading",
			"insert_after": "custom_section_bl_tracking",
			"in_list_view": 1,
		},
	)
	_create_cf(
		"Container Tracker",
		{
			"fieldname": "custom_bl_container_select",
			"label": "Container from B/L",
			"fieldtype": "Select",
			"insert_after": "custom_bill_of_lading",
			"depends_on": BL_DEPENDS,
			"description": "Select a container listed on the Bill of Lading, then complete tracking details below.",
		},
	)
	frappe.clear_cache(doctype="Container Tracker")
