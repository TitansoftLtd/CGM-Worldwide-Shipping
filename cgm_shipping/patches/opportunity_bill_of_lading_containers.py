"""Opportunity container table synced from linked Bill of Lading (schema only)."""
import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_shipment_fields import (
	_create_cf,
)

CONTAINER_DEPENDS = (
	"eval:doc.custom_bill_of_lading && ("
	"doc.custom_shipment_type == 'Sea FCL' || doc.custom_shipment_type == 'Sea LCL'"
	")"
)


def execute():
	_create_cf(
		"Opportunity",
		{
			"fieldname": "custom_container_information",
			"label": "Container Information",
			"fieldtype": "Table",
			"options": "Container",
			"insert_after": "custom_bill_of_lading",
			"depends_on": CONTAINER_DEPENDS,
			"read_only": 1,
			"cannot_add_rows": 1,
			"cannot_delete_rows": 1,
		},
	)
	_update_opportunity_field_order()
	frappe.clear_cache(doctype="Opportunity")


def _update_opportunity_field_order():
	ps_name = "Opportunity-main-field_order"
	if not frappe.db.exists("Property Setter", ps_name):
		return

	import json

	order = json.loads(frappe.db.get_value("Property Setter", ps_name, "value") or "[]")
	if "custom_container_information" in order:
		return

	try:
		idx = order.index("custom_bill_of_lading") + 1
	except ValueError:
		order.append("custom_container_information")
	else:
		order.insert(idx, "custom_container_information")

	frappe.db.set_value("Property Setter", ps_name, "value", json.dumps(order))
