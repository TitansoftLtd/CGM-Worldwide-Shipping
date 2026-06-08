// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bill of Lading", {
	refresh(frm) {
		// Branch a CRM Opportunity off a submitted Bill of Lading.
		if (frm.doc.docstatus !== 1) {
			return;
		}
		frm.add_custom_button(
			__("Opportunity"),
			() => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.bl_containers.create_opportunity_from_bill_of_lading",
					args: { bill_of_lading: frm.doc.name },
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
	},
});
