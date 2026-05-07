frappe.ui.form.on("Lead", {
	refresh(frm) {
		frm.remove_custom_button(__("Add to Prospect"), __("Create"));
		frm.remove_custom_button(__("Add to Prospect"));
		if (frm.doc.custom_cgm_preshipment_status !== "Lead Ready to Convert") {
			return;
		}
		frm.add_custom_button(
			__("Create Shipment Project"),
			() => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.utils.create_project_from_lead",
					args: { lead: frm.doc.name },
					freeze: true,
					callback(r) {
						if (!r.exc && r.message) {
							frappe.show_alert({
								message: __("Shipment Project created"),
								indicator: "green",
							});
							frappe.set_route("Form", "Project", r.message);
						}
					},
				});
			},
			__("Create")
		);
	},
});
