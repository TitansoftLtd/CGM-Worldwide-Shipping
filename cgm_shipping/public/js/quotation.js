// ============================================================
// CGM QUOTATION CLIENT SCRIPT
// ============================================================

// Tax types whose base accumulates (VAT stacks on top of prior duties).
// Populated dynamically from server metadata; seeded with known defaults.
const _STACKING_TYPES  = new Set(["VAT"]);
const _WEIGHT_TYPES    = new Set(["MSS Levy"]);
// Excise stacks on customs_value + import_duty only.
const _EXCISE_TYPES    = new Set(["Excise Duty"]);

// Cache of tax-type metadata fetched from server { [tax_type]: info }
const _TAX_TYPE_META   = {};

// ============================================================
// EXCHANGE RATE HELPERS
// ============================================================

function get_bank_rate(frm) {
    return flt(frm.doc.conversion_rate) || 1;
}

function get_customs_rate(frm, row) {
    return flt(row.exchange_rate) || get_bank_rate(frm);
}

// ============================================================
// IMPORT COST COMPONENT HELPERS
// ============================================================

function enforce_company_currency_exchange_rate(frm, cdt, cdn) {
    if (!frm.doc.company) return;
    frappe.model.with_doc("Company", frm.doc.company, () => {
        const company_currency = frappe.model.get_value(
            "Company", frm.doc.company, "default_currency"
        );
        const is_company_currency = frm.doc.currency === company_currency;

        if (is_company_currency) {
            frappe.model.set_value(cdt, cdn, "exchange_rate", 1);
        }

        frm.fields_dict.custom_import_cost_component?.grid
            .update_docfield_property("exchange_rate", "read_only",
                is_company_currency ? 1 : 0);
    });
}

function toggle_import_cost_exchange_rate(frm, cdt, cdn) {
    if (!frm.doc.company) return;
    frappe.model.with_doc("Company", frm.doc.company, () => {
        const company_currency = frappe.model.get_value(
            "Company", frm.doc.company, "default_currency"
        );
        const needs = frm.doc.currency && frm.doc.currency !== company_currency;
        frappe.model.set_value(cdt, cdn, "show_exchange_rate", needs ? 1 : 0);
    });
}

// ============================================================
// CUSTOMS VALUE CALCULATION
// ============================================================

function _compute_customs_value(frm) {
    let customs_value_foreign = 0;
    let customs_value_kes     = 0;

    (frm.doc.custom_import_cost_component || []).forEach(row => {
        const rate = get_customs_rate(frm, row);
        const kes  = flt(row.amount) * rate;

        row.amount_kes = kes;

        customs_value_foreign += flt(row.amount);
        customs_value_kes     += kes;
    });

    return { customs_value_foreign, customs_value_kes };
}

function _get_company_currency(frm) {
    if (frm.cscript && frm.cscript.get_company_currency) {
        return frm.cscript.get_company_currency();
    }
    return frappe.defaults.get_default("currency");
}

function _customs_tax_in_doc_currency(frm) {
    const company_currency = _get_company_currency(frm);
    const customs_kes = flt(frm.doc.custom_total_tax);
    if (frm.doc.currency === company_currency) {
        return customs_kes;
    }
    const rate = get_bank_rate(frm);
    return rate ? flt(customs_kes / rate) : 0;
}

function _update_grand_totals(frm) {
    const customs_kes = flt(frm.doc.custom_total_tax);
    const customs_doc = _customs_tax_in_doc_currency(frm);

    frm.doc.base_grand_total = flt(frm.doc.base_total) + customs_kes;
    frm.doc.grand_total = flt(frm.doc.total) + customs_doc;

    if (frm.doc.disable_rounded_total) {
        frm.doc.rounded_total = 0;
        frm.doc.base_rounded_total = 0;
        frm.doc.rounding_adjustment = 0;
        frm.doc.base_rounding_adjustment = 0;
    } else {
        const rounded_df = frappe.meta.get_docfield(frm.doc.doctype, "rounded_total");
        const base_rounded_df = frappe.meta.get_docfield(frm.doc.doctype, "base_rounded_total");
        const rounded_precision = frappe.meta.get_field_precision(rounded_df, frm.doc);
        const base_rounded_precision = frappe.meta.get_field_precision(base_rounded_df, frm.doc);

        frm.doc.rounded_total = round_based_on_smallest_currency_fraction(
            frm.doc.grand_total,
            frm.doc.currency,
            rounded_precision
        );
        frm.doc.rounding_adjustment = flt(frm.doc.rounded_total - frm.doc.grand_total);

        frm.doc.base_rounded_total = round_based_on_smallest_currency_fraction(
            frm.doc.base_grand_total,
            _get_company_currency(frm),
            base_rounded_precision
        );
        frm.doc.base_rounding_adjustment = flt(
            frm.doc.base_rounded_total - frm.doc.base_grand_total
        );
    }

    frm.refresh_fields([
        "grand_total",
        "base_grand_total",
        "rounded_total",
        "base_rounded_total",
        "rounding_adjustment",
        "base_rounding_adjustment",
    ]);

    _update_total_in_words(frm);
}

function _update_total_in_words(frm) {
    if (!frm.doc.company || !frm.doc.currency) {
        return;
    }

    frappe.call({
        method: "cgm_shipping.cgm_worldwide_shipping.customizations.quotation.get_total_in_words",
        args: {
            grand_total: frm.doc.grand_total,
            rounded_total: frm.doc.rounded_total,
            base_grand_total: frm.doc.base_grand_total,
            base_rounded_total: frm.doc.base_rounded_total,
            currency: frm.doc.currency,
            company: frm.doc.company,
            disable_rounded_total: frm.doc.disable_rounded_total,
        },
        callback(r) {
            if (!r.message) {
                return;
            }
            frm.doc.in_words = r.message.in_words;
            frm.doc.base_in_words = r.message.base_in_words;
            frm.refresh_fields(["in_words", "base_in_words"]);
        },
    });
}

function _sync_grand_totals_after_erpnext(frm) {
    if (frm.cscript && frm.cscript.calculate_taxes_and_totals) {
        const result = frm.cscript.calculate_taxes_and_totals();
        if (result && typeof result.then === "function") {
            result.then(() => _update_grand_totals(frm));
            return;
        }
    }
    _update_grand_totals(frm);
}

// ============================================================
// CUSTOMS TAX CALCULATION (live preview on custom_total_tax only)
// ============================================================

function calculate_customs_taxes(frm) {
    const weight_tons = flt(frm.doc.custom_weight) || 0;
    const { customs_value_kes } = _compute_customs_value(frm);

    let running_base_kes = customs_value_kes;
    let import_duty_kes  = 0;
    let total_taxes_kes  = 0;

    const tax_rows = [...(frm.doc.custom_customs_taxes || [])]
        .sort((a, b) => a.idx - b.idx);

    tax_rows.forEach(row => {
        if (!row.tax_type) return;

        const meta = _TAX_TYPE_META[row.tax_type] || {};
        let amount_kes = 0;

        if (flt(row.fixed_amount_kes) > 0 || meta.is_fixed) {
            amount_kes = flt(row.fixed_amount_kes);
        } else if (_WEIGHT_TYPES.has(row.tax_type) || meta.is_weight_based) {
            amount_kes = weight_tons * flt(row.rate);
        } else if (_EXCISE_TYPES.has(row.tax_type)) {
            const excise_base = customs_value_kes + import_duty_kes;
            amount_kes = excise_base * (flt(row.rate) / 100);
            running_base_kes += amount_kes;
        } else if (_STACKING_TYPES.has(row.tax_type) || meta.is_stacking) {
            amount_kes = running_base_kes * (flt(row.rate) / 100);
            running_base_kes += amount_kes;
        } else {
            amount_kes = customs_value_kes * (flt(row.rate) / 100);
            running_base_kes += amount_kes;

            if ((row.tax_type || "").toLowerCase().includes("import duty") ||
                (row.tax_type || "").toLowerCase().includes("duty") &&
                !(row.tax_type || "").toLowerCase().includes("excise")) {
                import_duty_kes += amount_kes;
            }
        }

        row.amount_kes = amount_kes;
        row.tax_amount_kes = amount_kes;
        total_taxes_kes += amount_kes;
    });

    frm.doc.custom_total_tax = total_taxes_kes;
    _update_grand_totals(frm);

    frm.refresh_fields([
        "custom_import_cost_component",
        "custom_customs_taxes",
        "custom_total_tax",
    ]);
}

// ============================================================
// CUSTOMS TAX ROW UI HELPERS
// ============================================================

function apply_customs_tax_defaults(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.tax_type) return;

    if (_TAX_TYPE_META[row.tax_type]) {
        _apply_meta_to_row(frm, cdt, cdn, _TAX_TYPE_META[row.tax_type]);
        return;
    }

    frappe.call({
        method: "cgm_shipping.cgm_worldwide_shipping.customizations.quotation.get_customs_tax_type_info",
        args: { tax_type: row.tax_type },
        callback(r) {
            if (!r.message) return;
            _TAX_TYPE_META[row.tax_type] = r.message;
            _apply_meta_to_row(frm, cdt, cdn, r.message);
        },
    });
}

function _apply_meta_to_row(frm, cdt, cdn, info) {
    if (info.default_rate != null) {
        frappe.model.set_value(cdt, cdn, "rate", info.default_rate);
    }

    frappe.model.set_value(cdt, cdn, "is_fixed_amount", info.is_fixed ? 1 : 0);

    const grid = frm.fields_dict.custom_customs_taxes?.grid;
    if (grid) {
        grid.update_docfield_property("rate", "label",
            info.is_weight_based ? "Rate per Ton (KES)" : "Rate (%)");
        grid.update_docfield_property("rate", "hidden",
            info.show_rate ? 0 : 1);
        grid.update_docfield_property("fixed_amount_kes", "hidden",
            info.show_fixed_amount ? 0 : 1);
        grid.refresh();
    }

    _toggle_row_read_only(frm, cdt, cdn, info.is_fixed);
    calculate_customs_taxes(frm);
}

function _toggle_row_read_only(frm, cdt, cdn, is_fixed) {
    const grid = frm.fields_dict.custom_customs_taxes?.grid;
    if (!grid) return;

    grid.update_docfield_property("rate",            "read_only", is_fixed ? 1 : 0);
    grid.update_docfield_property("fixed_amount_kes","read_only", is_fixed ? 0 : 1);
    grid.refresh();
}

function toggle_customs_tax_fields(frm, cdt, cdn) {
    const row     = locals[cdt][cdn];
    const is_fixed = flt(row.is_fixed_amount) === 1;
    const grid    = frm.fields_dict.custom_customs_taxes?.grid;
    if (!grid) return;

    grid.update_docfield_property("rate",            "hidden",    is_fixed ? 1 : 0);
    grid.update_docfield_property("fixed_amount_kes","hidden",    is_fixed ? 0 : 1);
    grid.update_docfield_property("rate",            "read_only", is_fixed ? 1 : 0);
    grid.update_docfield_property("fixed_amount_kes","read_only", is_fixed ? 0 : 1);
    grid.refresh();
}

// ============================================================
// QUOTATION FORM EVENTS
// ============================================================

frappe.ui.form.on("Quotation", {
    refresh(frm) {
        (frm.doc.custom_import_cost_component || []).forEach(row => {
            toggle_import_cost_exchange_rate(frm, row.doctype, row.name);
        });
        (frm.doc.custom_customs_taxes || []).forEach(row => {
            toggle_customs_tax_fields(frm, row.doctype, row.name);
        });

        calculate_customs_taxes(frm);
    },

    company(frm) {
        calculate_customs_taxes(frm);
    },

    currency(frm) {
        calculate_customs_taxes(frm);
    },

    conversion_rate(frm) {
        calculate_customs_taxes(frm);
    },

    custom_weight(frm) {
        calculate_customs_taxes(frm);
    },
});

frappe.ui.form.on("Quotation Item", {
    rate(frm) {
        _sync_grand_totals_after_erpnext(frm);
    },

    qty(frm) {
        _sync_grand_totals_after_erpnext(frm);
    },

    amount(frm) {
        _sync_grand_totals_after_erpnext(frm);
    },

    items_remove(frm) {
        _sync_grand_totals_after_erpnext(frm);
    },
});

// ============================================================
// IMPORT COST COMPONENT CHILD TABLE EVENTS
// ============================================================

frappe.ui.form.on("Import Cost Component", {
    custom_import_cost_component_add(frm) {
        calculate_customs_taxes(frm);
    },

    custom_import_cost_component_remove(frm) {
        calculate_customs_taxes(frm);
    },

    exchange_rate(frm) {
        calculate_customs_taxes(frm);
    },

    amount(frm) {
        calculate_customs_taxes(frm);
    },

    form_render(frm, cdt, cdn) {
        enforce_company_currency_exchange_rate(frm, cdt, cdn);
        toggle_import_cost_exchange_rate(frm, cdt, cdn);
    },
});

// ============================================================
// CUSTOMS TAX COMPONENT CHILD TABLE EVENTS
// ============================================================

frappe.ui.form.on("Customs Tax Component", {
    custom_customs_taxes_add(frm) {
        calculate_customs_taxes(frm);
    },

    custom_customs_taxes_remove(frm) {
        calculate_customs_taxes(frm);
    },

    tax_type(frm, cdt, cdn) {
        apply_customs_tax_defaults(frm, cdt, cdn);
    },

    rate(frm) {
        calculate_customs_taxes(frm);
    },

    fixed_amount_kes(frm) {
        calculate_customs_taxes(frm);
    },

    is_fixed_amount(frm, cdt, cdn) {
        toggle_customs_tax_fields(frm, cdt, cdn);
        calculate_customs_taxes(frm);
    },

    form_render(frm, cdt, cdn) {
        toggle_customs_tax_fields(frm, cdt, cdn);
    },
});
