// Item Pricing Rule grid — refresh row form when calculation type changes.

frappe.ui.form.on("Item Pricing Rule", {
	calculation_type(frm, cdt, cdn) {
		frm.fields_dict.custom_item_pricing_rules?.grid?.refresh();
	},
});
