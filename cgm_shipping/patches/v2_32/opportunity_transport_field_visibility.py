import frappe

FIELD_DEPENDS = {
	"Opportunity-custom_airway_bill": "eval:doc.custom_mode_of_transport == 'Air'",
	"Opportunity-custom_air_waybill": "eval:doc.custom_mode_of_transport == 'Air'",
	"Opportunity-custom_bill_of_lading": "eval:doc.custom_mode_of_transport == 'Sea'",
	"Opportunity-custom_section_break_idqn5": (
		"eval:doc.custom_mode_of_transport == 'Sea' || doc.custom_mode_of_transport == 'Air'"
	),
}


def execute():
	for name, depends_on in FIELD_DEPENDS.items():
		if frappe.db.exists("Custom Field", name):
			frappe.db.set_value("Custom Field", name, "depends_on", depends_on)
	frappe.clear_cache(doctype="Opportunity")
