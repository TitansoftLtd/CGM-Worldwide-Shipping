frappe.ui.form.on("Clearance Charge Item", {
	refresh(frm) {
		frm.set_query("purchase_item", function () {
			return {
				filters: { disabled: 0, is_purchase_item: 1 },
			};
		});
		frm.toggle_display("allows_amendment", frm.doc.line_type === "Invoice");
		if (!frm.is_new()) {
			frm.set_intro(
				__(
					"This name appears as the Item on Task finance lines. Use <b>Menu → Rename</b> to change the charge name. " +
						"For Invoice charges, enable <b>Allows Amendment Invoices</b> so Declarant can add extra invoices after the first payment (Sea Clearance behaviour)."
				),
				"blue"
			);
		} else {
			frm.set_intro("");
		}
	},
	line_type(frm) {
		frm.toggle_display("allows_amendment", frm.doc.line_type === "Invoice");
		if (frm.doc.line_type !== "Invoice" && cint(frm.doc.allows_amendment)) {
			frm.set_value("allows_amendment", 0);
		}
	},
});
