/*!
 * Supplier form helpers — shipping-line charge rules only when flagged.
 */
frappe.ui.form.on("Supplier", {
	refresh(frm) {
		toggle_shipping_line_sections(frm);
	},
	custom_is_shipping_line(frm) {
		toggle_shipping_line_sections(frm);
	},
	is_transporter(frm) {
		toggle_shipping_line_sections(frm);
	},
});

function toggle_shipping_line_sections(frm) {
	const is_line = cint(frm.doc.custom_is_shipping_line);
	[
		"custom_section_shipping_line_rules",
		"custom_shipping_line_free_days_rules",
		"custom_shipping_line_demurrage_tiers",
	].forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_display(fieldname, is_line);
		}
	});
}
