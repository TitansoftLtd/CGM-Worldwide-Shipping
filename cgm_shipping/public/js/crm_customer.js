frappe.ui.form.on("Customer", {
	refresh(frm) {
		// Hide the standard ERPNext "Create" options so only the CGM
		// shipping documents (Bill of Lading & Air Waybill) remain.
		[
			"Quotation",
			"Sales Order",
			"Opportunity",
			"Payment Entry",
			"Pricing Rule",
			"Bank Account",
		].forEach((label) => {
			frm.remove_custom_button(__(label), __("Create"));
		});

		frm.add_custom_button(
			__("Bill of Lading"),
			() => {
				frappe.new_doc("Bill of Lading", { customer: frm.doc.name });
			},
			__("Create")
		);

		frm.add_custom_button(
			__("Air Waybill"),
			() => {
				frappe.new_doc("Air Waybill", { customer: frm.doc.name });
			},
			__("Create")
		);

		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});
