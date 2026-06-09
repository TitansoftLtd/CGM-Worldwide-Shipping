frappe.ui.form.on("Customer", {
	refresh(frm) {
		frm.add_custom_button(
			__("Bill of Lading"),
			() => {
				frappe.new_doc("Bill of Lading", { customer: frm.doc.name });
			},
			__("Create")
		);

		frm.add_custom_button(
			__("Create Shipment Project"),
			() => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.utils.create_project_from_customer",
					args: { customer: frm.doc.name },
					freeze: true,
					callback(r) {
						if (!r.exc && r.message) {
							frappe.show_alert({
								message: __(
									"Shipment Project created. Sea tasks 1–2 are auto-completed when CI/PKL came from CRM."
								),
								indicator: "green",
							});
							frappe.set_route("Form", "Project", r.message);
						}
					},
				});
			},
			__("Create")
		);

		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});
