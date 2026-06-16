// ============================================================
// CURRENCY HELPERS
// ============================================================

/**
 * Warms the Company doc into frappe.locals cache, then runs a callback.
 * All currency label rendering depends on this being loaded first.
 */
function with_company_currency(frm, callback) {
	if (!frm.doc.company) return;
	frappe.model.with_doc("Company", frm.doc.company, () => {
		const company_currency = frappe.model.get_value(
			"Company",
			frm.doc.company,
			"default_currency"
		);
		callback(company_currency);
	});
}

/**
 * Dynamically updates ALL Currency field labels on the form and all child
 * tables — no hardcoded field names. Any field with:
 *   options: "currency"                       → gets "(EUR)" / "(USD)" etc.
 *   options: "Company:company:default_currency" → gets "(KES)" etc.
 * Adding a new Currency field with the right options is all that's needed.
 */
function setup_currency_labels(frm) {
	with_company_currency(frm, (company_currency) => {
		const transaction_currency = frm.doc.currency;

		// ── Parent doc fields ──────────────────────────────────
		frm.meta.fields.forEach((df) => {
			if (df.fieldtype !== "Currency") return;

			if (
				df.options === "Company:company:default_currency" ||
				df.options === "company_currency"
			) {
				frm.set_df_property(
					df.fieldname,
					"label",
					_currency_label(df.label, company_currency)
				);
			} else if (df.options === "currency") {
				frm.set_df_property(
					df.fieldname,
					"label",
					_currency_label(df.label, transaction_currency)
				);
			}
		});

		// ── All child tables on the form ───────────────────────
		frm.meta.fields
			.filter((df) => df.fieldtype === "Table")
			.forEach((table_df) => {
				const child_meta = frappe.get_meta(table_df.options);
				if (!child_meta) return;

				const grid = frm.fields_dict[table_df.fieldname]?.grid;
				if (!grid) return;

				child_meta.fields.forEach((df) => {
					if (df.fieldtype !== "Currency") return;

					if (
						df.options === "Company:company:default_currency" ||
						df.options === "company_currency"
					) {
						grid.update_docfield_property(
							df.fieldname,
							"label",
							_currency_label(df.label, company_currency)
						);
					} else if (df.options === "currency") {
						grid.update_docfield_property(
							df.fieldname,
							"label",
							_currency_label(df.label, transaction_currency)
						);
					}
				});

				grid.refresh();
			});

		frm.refresh_fields();
	});
}

/**
 * Strips any existing "(XXX)" currency suffix from a label and appends
 * the current one. e.g. "Amount (EUR)" → "Amount (KES)"
 */
function _currency_label(label, currency) {
	if (!currency) return label;
	return label.replace(/ \(.*?\)$/, "") + ` (${currency})`;
}

// ============================================================
// IMPORT COST COMPONENT HELPERS
// ============================================================

/**
 * If the row's currency is KES, lock exchange_rate to 1 and make it
 * read-only. Otherwise unlock it.
 */
function enforce_kes_exchange_rate(frm, cdt, cdn) {
	with_company_currency(frm, (company_currency) => {
		const row = locals[cdt][cdn];
		if (row.currency === company_currency) {
			frappe.model.set_value(cdt, cdn, "exchange_rate", 1);
			frm.fields_dict.custom_import_cost_component.grid.update_docfield_property(
				"exchange_rate",
				"read_only",
				1
			);
		} else {
			frm.fields_dict.custom_import_cost_component.grid.update_docfield_property(
				"exchange_rate",
				"read_only",
				0
			);
		}
	});
}

/**
 * Show exchange_rate field only when the row currency differs from
 * the company currency (i.e. a conversion is actually needed).
 */
function toggle_import_cost_exchange_rate(frm, cdt, cdn) {
	with_company_currency(frm, (company_currency) => {
		const row = locals[cdt][cdn];
		const needs_conversion = row.currency && row.currency !== company_currency;
		frappe.model.set_value(
			cdt,
			cdn,
			"show_exchange_rate",
			needs_conversion ? 1 : 0
		);
	});
}

// ============================================================
// CUSTOMS TAX HELPERS
// ============================================================

/** Auto-fill rate/fixed_amount defaults when a tax type is selected. */
function apply_customs_tax_defaults(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const defaults = {
		"Import Duty": { rate: 25, fixed_amount_kes: 0 },
		"VAT": { rate: 16, fixed_amount_kes: 0 },
		"IDF": { rate: 2.25, fixed_amount_kes: 0 },
		"Railway Development Levy": { rate: 1.5, fixed_amount_kes: 0 },
		"Import Declaration Fee": { rate: 0, fixed_amount_kes: 5000 },
	};

	if (defaults[row.tax_type]) {
		frappe.model.set_value(cdt, cdn, "rate", defaults[row.tax_type].rate);
		frappe.model.set_value(
			cdt,
			cdn,
			"fixed_amount_kes",
			defaults[row.tax_type].fixed_amount_kes
		);
	}
	toggle_customs_tax_fields(frm, cdt, cdn);
}

/**
 * Show rate field for percentage taxes, fixed_amount_kes for fixed taxes.
 * Hides the field that does not apply to the selected tax type.
 */
function toggle_customs_tax_fields(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const fixed_types = ["Import Declaration Fee"];
	const is_fixed = fixed_types.includes(row.tax_type);

	frappe.model.set_value(cdt, cdn, "is_fixed_amount", is_fixed ? 1 : 0);
}

// ============================================================
// CALCULATION ENGINE
// ============================================================

/**
 * Master recalculation — runs top to bottom:
 *  1. Sum Import Cost Component rows → base customs value (KES)
 *  2. Apply Customs Tax rows against that base → total taxes (KES)
 *  3. Write summary fields back to the Quotation
 */
function calculate_customs_taxes(frm) {
	const conversion_rate = flt(frm.doc.conversion_rate) || 1;

	// ── Step 1: Total import costs in KES ─────────────────────
	let base_customs_value_kes = 0;

	(frm.doc.custom_import_cost_component || []).forEach((row) => {
		const row_rate = flt(row.exchange_rate) || conversion_rate;
		const amount_kes = flt(row.amount) * row_rate;

		// Write the KES equivalent back into the row
		frappe.model.set_value(
			row.doctype,
			row.name,
			"amount_kes",
			amount_kes
		);

		base_customs_value_kes += amount_kes;
	});

	// ── Step 2: Apply each customs tax ────────────────────────
	let total_taxes_kes = 0;
	let running_base = base_customs_value_kes; // some taxes stack

	(frm.doc.custom_customs_taxes || []).forEach((row) => {
		let tax_amount_kes = 0;

		if (flt(row.fixed_amount_kes) > 0) {
			// Fixed amount tax
			tax_amount_kes = flt(row.fixed_amount_kes);
		} else if (flt(row.rate) > 0) {
			// Percentage tax against running base
			tax_amount_kes = (running_base * flt(row.rate)) / 100;
			running_base += tax_amount_kes; // stack for next tax
		}

		frappe.model.set_value(
			row.doctype,
			row.name,
			"tax_amount_kes",
			tax_amount_kes
		);

		total_taxes_kes += tax_amount_kes;
	});

	// ── Step 3: Write summary back to Quotation ───────────────
	frm.set_value("custom_base_customs_value", base_customs_value_kes);
	frm.set_value(
		"custom_custom_value",
		base_customs_value_kes / conversion_rate // back to transaction currency
	);
	frm.set_value("custom_total_taxes_kes", total_taxes_kes);

	frm.refresh_fields([
		"custom_import_cost_component",
		"custom_customs_taxes",
		"custom_base_customs_value",
		"custom_custom_value",
		"custom_total_taxes_kes",
	]);
}

// ============================================================
// QUOTATION FORM EVENTS
// ============================================================

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		// Currency labels first — everything else depends on company cache being warm
		setup_currency_labels(frm);

		// Apply per-row UI rules to existing rows
		(frm.doc.custom_import_cost_component || []).forEach((row) => {
			toggle_import_cost_exchange_rate(frm, row.doctype, row.name);
		});
		(frm.doc.custom_customs_taxes || []).forEach((row) => {
			toggle_customs_tax_fields(frm, row.doctype, row.name);
		});

		calculate_customs_taxes(frm);
	},

	company(frm) {
		// Company changed → company currency may have changed → full relabel
		setup_currency_labels(frm);
	},

	currency(frm) {
		// Transaction currency changed → relabel + recalculate bases
		setup_currency_labels(frm);
		calculate_customs_taxes(frm);
	},

	conversion_rate(frm) {
		// Rate changed → recalculate KES amounts
		calculate_customs_taxes(frm);
	},

	custom_import_cost_component_remove(frm) {
		calculate_customs_taxes(frm);
	},

	custom_customs_taxes_remove(frm) {
		calculate_customs_taxes(frm);
	},
});

// ============================================================
// IMPORT COST COMPONENT CHILD TABLE EVENTS
// ============================================================

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
		// Re-apply rules each time a row dialog opens
		enforce_kes_exchange_rate(frm, cdt, cdn);
		toggle_import_cost_exchange_rate(frm, cdt, cdn);
	},
});

// ============================================================
// CUSTOMS TAX COMPONENT CHILD TABLE EVENTS
// ============================================================

frappe.ui.form.on("Customs Tax Component", {
	tax_type(frm, cdt, cdn) {
		apply_customs_tax_defaults(frm, cdt, cdn);
		calculate_customs_taxes(frm);
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
