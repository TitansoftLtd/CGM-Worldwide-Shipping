frappe.ui.form.on("Customer", {
	refresh(frm) {
		frm.add_custom_button(
			__("Create Shipment Project"),
			() => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.shipment_project_api.create_project_from_customer",
					args: { customer: frm.doc.name },
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
