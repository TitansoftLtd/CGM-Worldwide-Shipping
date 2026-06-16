frappe.ui.form.on("Quotation", {
	refresh(frm) {
		(frm.doc.custom_import_cost_component || []).forEach((row) => {
			toggle_import_cost_exchange_rate(frm, row.doctype, row.name);
		});
		(frm.doc.custom_customs_taxes || []).forEach((row) => {
			toggle_customs_tax_fields(frm, row.doctype, row.name);
		});
		calculate_customs_taxes(frm);
	},

	custom_import_cost_component_remove(frm) {
		calculate_customs_taxes(frm);
	},

	custom_customs_taxes_remove(frm) {
		calculate_customs_taxes(frm);
	},
});

frappe.ui.form.on("Import Cost Component", {
	currency(frm, cdt, cdn) {
		enforce_kes_exchange_rate(frm, cdt, cdn);
		toggle_import_cost_exchange_rate(frm, cdt, cdn);
		calculate_customs_taxes(frm);
	},

	exchange_rate(frm, cdt, cdn) {
		enforce_kes_exchange_rate(frm, cdt, cdn);
		calculate_customs_taxes(frm);
	},

	amount(frm) {
		calculate_customs_taxes(frm);
	},

	form_render(frm, cdt, cdn) {
		enforce_kes_exchange_rate(frm, cdt, cdn);
		toggle_import_cost_exchange_rate(frm, cdt, cdn);
	},
});

frappe.ui.form.on("Customs Tax Component", {
	tax_type(frm, cdt, cdn) {
		apply_customs_tax_defaults(frm, cdt, cdn);
	},

	rate(frm) {
		calculate_customs_taxes(frm);
	},

	fixed_amount_kes(frm) {
		calculate_customs_taxes(frm);
	},

	form_render(frm, cdt, cdn) {
		toggle_customs_tax_fields(frm, cdt, cdn);
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

function apply_customs_tax_defaults(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.tax_type) {
		return;
	}

	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.quotation.get_customs_tax_type_info",
		args: { tax_type: row.tax_type },
		callback({ message }) {
			if (!message) {
				return;
			}

			const tasks = [];
			if (message.uses_fixed_amount) {
				tasks.push(frappe.model.set_value(cdt, cdn, "rate", 0));
			} else if (message.uses_default_rate && message.default_rate != null) {
				tasks.push(frappe.model.set_value(cdt, cdn, "rate", message.default_rate));
				tasks.push(frappe.model.set_value(cdt, cdn, "fixed_amount_kes", 0));
			} else if (message.uses_manual_rate) {
				tasks.push(frappe.model.set_value(cdt, cdn, "rate", 0));
				tasks.push(frappe.model.set_value(cdt, cdn, "fixed_amount_kes", 0));
			}

			Promise.all(tasks).then(() => {
				toggle_customs_tax_fields(frm, cdt, cdn);
				calculate_customs_taxes(frm);
			});
		},
	});
}

function toggle_customs_tax_fields(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const grid = frm.fields_dict.custom_customs_taxes?.grid;
	if (!grid || !row.tax_type) {
		return;
	}

	const grid_row = grid.grid_rows_by_docname?.[cdn] || grid.get_row(cdn);
	if (!grid_row) {
		return;
	}

	frappe.db.get_value("Customs Tax Type", row.tax_type, "calculation_type").then(({ message }) => {
		const is_fixed = message?.calculation_type === "Fixed Amount";
		grid_row.toggle_editable("rate", !is_fixed);
		grid_row.toggle_editable("fixed_amount_kes", is_fixed);
	});
}

async function get_usd_to_kes_rate(frm) {
	const company_currency = get_quotation_company_currency(frm);

	for (const row of frm.doc.custom_import_cost_component || []) {
		if (row.currency === "USD" && flt(row.exchange_rate)) {
			return flt(row.exchange_rate);
		}
	}

	if (frm.doc.currency === "USD" && flt(frm.doc.conversion_rate)) {
		return flt(frm.doc.conversion_rate);
	}

	if (!company_currency) {
		return 0;
	}

	const { message } = await frappe.db.get_value(
		"Currency Exchange",
		{
			from_currency: "USD",
			to_currency: company_currency,
		},
		"exchange_rate",
	);

	return flt(message?.exchange_rate);
}

function calculate_import_cost_amount_kes(row, company_currency) {
	const amount = flt(row.amount);
	if (!row.currency || row.currency === company_currency) {
		return amount;
	}
	return flt(amount * flt(row.exchange_rate));
}

async function calculate_customs_value(frm) {
	const company_currency = get_quotation_company_currency(frm);
	let customs_value_kes = 0;
	let usd_total = 0;
	let kes_total = 0;

	for (const row of frm.doc.custom_import_cost_component || []) {
		const amount_kes = calculate_import_cost_amount_kes(row, company_currency);
		row.amount_kes = amount_kes;
		customs_value_kes += amount_kes;

		if (row.currency === "USD") {
			usd_total += flt(row.amount);
		} else if (row.currency === company_currency) {
			kes_total += flt(row.amount);
		} else {
			kes_total += amount_kes;
		}
	}

	const usd_to_kes_rate = await get_usd_to_kes_rate(frm);
	const kes_in_usd = usd_to_kes_rate ? flt(kes_total / usd_to_kes_rate) : 0;

	return {
		customs_value_kes,
		customs_value_usd: usd_total + kes_in_usd,
		usd_to_kes_rate,
	};
}

async function calculate_customs_taxes(frm) {
	if (!frm.fields_dict.custom_customs_taxes) {
		return;
	}

	const { customs_value_kes, customs_value_usd, usd_to_kes_rate } = await calculate_customs_value(frm);
	let total_taxes_kes = 0;
	let total_taxes_usd = 0;

	for (const row of frm.doc.custom_customs_taxes || []) {
		if (!row.tax_type) {
			await frappe.model.set_value(row.doctype, row.name, "amount_kes", 0);
			await frappe.model.set_value(row.doctype, row.name, "amount_usd", 0);
			continue;
		}

		const { message } = await frappe.db.get_value(
			"Customs Tax Type",
			row.tax_type,
			"calculation_type",
		);

		let amount_kes = 0;
		if (message?.calculation_type === "Fixed Amount") {
			amount_kes = flt(row.fixed_amount_kes);
		} else {
			amount_kes = flt(customs_value_kes * (flt(row.rate) / 100));
		}

		const amount_usd = usd_to_kes_rate ? flt(amount_kes / usd_to_kes_rate) : 0;
		await frappe.model.set_value(row.doctype, row.name, "amount_kes", amount_kes);
		await frappe.model.set_value(row.doctype, row.name, "amount_usd", amount_usd);
		total_taxes_kes += amount_kes;
		total_taxes_usd += amount_usd;
	}

	frm.set_value("custom_customs_value_kes", customs_value_kes);
	frm.set_value("custom_customs_value_usd", customs_value_usd);
	if (frm.fields_dict.custom_total_taxes_kes) {
		frm.set_value("custom_total_taxes_kes", total_taxes_kes);
	}
	if (frm.fields_dict.custom_total_taxes_usd) {
		frm.set_value("custom_total_taxes_usd", total_taxes_usd);
	}
}
