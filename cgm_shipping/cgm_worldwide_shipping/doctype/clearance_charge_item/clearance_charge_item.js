frappe.ui.form.on("Clearance Charge Item", {
	refresh(frm) {
		frm.set_query("purchase_item", function () {
			return {
				filters: { disabled: 0, is_purchase_item: 1 },
			};
		});
		if (!frm.is_new()) {
			frm.set_intro(
				__(
					"This name appears as the Item on Task finance lines. Use <b>Menu → Rename</b> to change the charge name."
				),
				"blue"
			);
		} else {
			frm.set_intro("");
		}
	},
});
