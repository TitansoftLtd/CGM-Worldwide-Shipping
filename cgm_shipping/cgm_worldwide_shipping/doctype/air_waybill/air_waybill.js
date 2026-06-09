// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("Air Waybill", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			add_create_opportunity_button(frm);
		}
	},
});

function add_create_opportunity_button(frm) {
	if (frm.doc.linked_opportunity) {
		frm.add_custom_button(
			__("Opportunity"),
			() => frappe.set_route("Form", "Opportunity", frm.doc.linked_opportunity),
			__("View")
		);
		frm.page.set_inner_btn_group_as_primary(__("View"));
		return;
	}

	// Branch a CRM Opportunity off a submitted Air Waybill.
	frm.add_custom_button(
		__("Opportunity"),
		() => {
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.doctype.air_waybill.air_waybill.create_opportunity_from_air_waybill",
				args: { air_waybill: frm.doc.name },
				freeze: true,
				callback(r) {
					if (!r.exc && r.message) {
						frappe.show_alert({
							message: __("Opportunity {0} created", [r.message]),
							indicator: "green",
						});
						frappe.set_route("Form", "Opportunity", r.message);
					}
				},
			});
		},
		__("Create")
	);
	frm.page.set_inner_btn_group_as_primary(__("Create"));
}
