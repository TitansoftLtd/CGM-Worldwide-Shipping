frappe.ui.form.on("Customer", {
	refresh(frm) {
		// Keep Opportunity as the only available document in the Create menu.
		[
			"Quotation",
			"Sales Order",
			"Payment Entry",
			"Pricing Rule",
			"Bank Account",
		].forEach((label) => {
			frm.remove_custom_button(__(label), __("Create"));
		});

		frm.remove_custom_button(__("Bill of Lading"), __("Create"));
		frm.remove_custom_button(__("Air Waybill"), __("Create"));

		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});
