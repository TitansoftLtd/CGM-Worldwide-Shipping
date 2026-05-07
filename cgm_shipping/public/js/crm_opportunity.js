frappe.ui.form.on("Opportunity", {
	refresh(frm) {
		if (
			frm.doc.custom_cgm_preshipment_status !== "Opp Ready for Project" ||
			frm.doc.opportunity_from !== "Customer"
		) {
			return;
		}
		frm.add_custom_button(
			__("Create Shipment Project"),
			() => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.shipment_project_api.create_project_from_opportunity",
					args: { opportunity: frm.doc.name },
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
