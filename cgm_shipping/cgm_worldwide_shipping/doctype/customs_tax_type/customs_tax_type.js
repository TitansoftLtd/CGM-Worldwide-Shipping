// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("Customs Tax Type", {
	refresh(frm) {
		frm.set_query("default_calculation_mode", () => ({
			filters: {
				name: ["in", (frm.doc.allowed_calculation_modes || []).map((r) => r.calculation_mode)],
			},
		}));
	},

	allowed_calculation_modes(frm) {
		const allowed = (frm.doc.allowed_calculation_modes || [])
			.map((r) => r.calculation_mode)
			.filter(Boolean);
		if (
			frm.doc.default_calculation_mode &&
			allowed.length &&
			!allowed.includes(frm.doc.default_calculation_mode)
		) {
			frm.set_value("default_calculation_mode", allowed[0]);
		}
	},
});
