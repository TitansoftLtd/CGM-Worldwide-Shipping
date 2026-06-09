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
			__("Air Waybill"),
			() => {
				frappe.new_doc("Air Waybill", { customer: frm.doc.name });
			},
			__("Create")
		);

		frm.page.set_inner_btn_group_as_primary(__("Create"));
	},
});
