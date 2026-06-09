"""Shipment-type-based visibility for Opportunity transport reference fields."""
import frappe

SEA_SHIPMENT_EXPR = (
	"eval:doc.custom_shipment_type == 'Sea FCL' || doc.custom_shipment_type == 'Sea LCL'"
)

AIR_SHIPMENT_EXPR = "eval:doc.custom_shipment_type == 'Air Import'"

SEA_OR_AIR_SHIPMENT_EXPR = (
	"eval:doc.custom_shipment_type == 'Sea FCL'"
	" || doc.custom_shipment_type == 'Sea LCL'"
	" || doc.custom_shipment_type == 'Air Import'"
)

CONTAINER_DEPENDS = (
	"eval:doc.custom_bill_of_lading && ("
	"doc.custom_shipment_type == 'Sea FCL' || doc.custom_shipment_type == 'Sea LCL'"
	")"
)

FIELD_DEPENDS = {
	"Opportunity-custom_bill_of_lading": SEA_SHIPMENT_EXPR,
	"Opportunity-custom_air_waybill": AIR_SHIPMENT_EXPR,
	"Opportunity-custom_section_break_idqn5": SEA_OR_AIR_SHIPMENT_EXPR,
	"Opportunity-custom_container_information": CONTAINER_DEPENDS,
}


def execute():
	for name, depends_on in FIELD_DEPENDS.items():
		if frappe.db.exists("Custom Field", name):
			frappe.db.set_value("Custom Field", name, "depends_on", depends_on)
	frappe.clear_cache(doctype="Opportunity")
