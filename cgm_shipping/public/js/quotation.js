frappe.ui.form.on("Quotation", {
	refresh(frm) {
		(frm.doc.custom_import_cost_component || []).forEach((row) => {
			toggle_import_cost_exchange_rate(frm, row.doctype, row.name);
		});
	},
});

frappe.ui.form.on("Import Cost Component", {
	currency(frm, cdt, cdn) {
		enforce_kes_exchange_rate(frm, cdt, cdn);
		toggle_import_cost_exchange_rate(frm, cdt, cdn);
	},

	exchange_rate(frm, cdt, cdn) {
		enforce_kes_exchange_rate(frm, cdt, cdn);
	},

	form_render(frm, cdt, cdn) {
		enforce_kes_exchange_rate(frm, cdt, cdn);
		toggle_import_cost_exchange_rate(frm, cdt, cdn);
	},
});

function get_quotation_company_currency(frm) {
	if (!frm.doc.company) {
		return null;
	}

	return frappe.get_doc(":Company", frm.doc.company)?.default_currency || null;
}

function is_kes_currency(frm, currency) {
	const company_currency = get_quotation_company_currency(frm);
	return currency && company_currency && currency === company_currency;
}

function enforce_kes_exchange_rate(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!is_kes_currency(frm, row.currency)) {
		return;
	}

	if (flt(row.exchange_rate) !== 1) {
		frappe.model.set_value(cdt, cdn, "exchange_rate", 1);
	}
}

function toggle_import_cost_exchange_rate(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const grid = frm.fields_dict.custom_import_cost_component?.grid;
	if (!grid) {
		return;
	}

	const grid_row = grid.grid_rows_by_docname?.[cdn] || grid.get_row(cdn);
	if (!grid_row) {
		return;
	}

	const read_only = is_kes_currency(frm, row.currency);
	grid_row.toggle_editable("exchange_rate", !read_only);
}
