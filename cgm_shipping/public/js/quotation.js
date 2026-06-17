// ============================================================
// CGM QUOTATION CLIENT SCRIPT
// ============================================================
//
// TWO EXCHANGE RATES — this is the core design principle:
//
//   1. row.exchange_rate  (on Import Cost Component)
//      → Company-chosen rate for customs value calculation.
//      → Each row can have its OWN rate.
//
//   2. frm.doc.conversion_rate  (on the Quotation itself — bank rate)
//      → Used for ALL local charges (Quotation Items).
//      → Used to convert taxes back to transaction currency for grand total.
//
// Customs Value (Foreign Currency) = sum of row.amount (raw foreign amounts).
// Customs Value (KES) = sum of row.amount * row.exchange_rate.
//
// Tax stacking order (matches Python):
//   Import Duty   = customs_value_kes × rate%
//   Excise Duty   = (customs_value_kes + import_duty) × rate%
//   IDF           = customs_value_kes × rate%
//   RDL           = customs_value_kes × rate%
//   VAT           = (customs_value_kes + all prior duties) × rate%
//   MSS Levy      = weight_tons × rate_per_ton  OR  fixed_amount
//   Other flat    = customs_value_kes × rate%
//
// All stacking behaviour is driven by the Customs Tax Type doctype flags,
// not by hardcoded tax-type names.
// ============================================================

const KES_OPTIONS = ["Company:company:default_currency", "company_currency"];

// Tax types whose base accumulates (VAT stacks on top of prior duties).
// Populated dynamically from server metadata; seeded with known defaults.
const _STACKING_TYPES  = new Set(["VAT"]);
const _WEIGHT_TYPES    = new Set(["MSS Levy"]);
// Excise stacks on customs_value + import_duty only.
const _EXCISE_TYPES    = new Set(["Excise Duty"]);

// Cache of tax-type metadata fetched from server { [tax_type]: info }
const _TAX_TYPE_META   = {};

// ============================================================
// CURRENCY LABEL HELPERS
// ============================================================

function setup_currency_labels(frm) {
    if (!frm.doc.company) return;

    frappe.model.with_doc("Company", frm.doc.company, () => {
    const company_currency = frappe.model.get_value(
        "Company", frm.doc.company, "default_currency"
    );
    const txn_currency = frm.doc.currency || company_currency;

    if (frm.fields_dict.custom_custom_value) {
        frm.set_df_property(
            "custom_custom_value",
            "options",
            "currency"
        );
    }

    if (frm.fields_dict.custom_base_customs_value) {
        frm.set_df_property(
            "custom_base_customs_value",
            "options",
            "Company:company:default_currency"
        );
    }

    if (frm.fields_dict.custom_total_taxes_kes) {
        frm.set_df_property(
            "custom_total_taxes_kes",
            "options",
            "Company:company:default_currency"
        );
    }

    frm.refresh_fields([
        "custom_custom_value",
        "custom_base_customs_value",
        "custom_total_taxes_kes"
    ]);
});
}

function _relabel_fields(frm, fields, grid, company_currency, txn_currency) {
    (fields || []).forEach(df => {
        if (df.fieldtype !== "Currency") return;
        let new_label = null;
        const options = (df.options || "").trim();

    if (KES_OPTIONS.includes(options)) {
            new_label = _currency_label(df.label, company_currency);
        } else if (df.options === "currency") {
            new_label = _currency_label(df.label, txn_currency);
        }
        if (!new_label) return;
        if (grid) {
            grid.update_docfield_property(df.fieldname, "label", new_label);
        } else {
            frm.set_df_property(df.fieldname, "label", new_label);
        }
    });
}

function _currency_label(label, currency) {
    if (!currency) return label;
    return label.replace(/ \(.*?\)$/, "") + ` (${currency})`;
}

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
        const row = locals[cdt][cdn];
        const is_company_currency = row.currency === company_currency;

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
        const row = locals[cdt][cdn];
        const needs = row.currency && row.currency !== company_currency;
        frappe.model.set_value(cdt, cdn, "show_exchange_rate", needs ? 1 : 0);
    });
}

// ============================================================
// CUSTOMS VALUE CALCULATION
// ============================================================

/**
 * Returns { customs_value_foreign, customs_value_kes }
 *
 * customs_value_foreign = sum of row.amount   (raw foreign amounts, no conversion)
 * customs_value_kes     = sum of row.amount * row.exchange_rate
 *
 * The "foreign" total uses amounts as entered in the child table.
 * It does NOT convert back from KES — that would lose precision.
 */
function _compute_customs_value(frm) {
    let customs_value_foreign = 0;
    let customs_value_kes     = 0;

    (frm.doc.custom_import_cost_component || []).forEach(row => {
        const rate = get_customs_rate(frm, row);
        const kes  = flt(row.amount) * rate;

        frappe.model.set_value(row.doctype, row.name, "amount_kes", kes);

        customs_value_foreign += flt(row.amount);
        customs_value_kes     += kes;
    });

    return { customs_value_foreign, customs_value_kes };
}

// ============================================================
// CUSTOMS TAX CALCULATION (client-side preview)
// ============================================================

/**
 * Full recalculation.
 *
 * Stacking logic (mirrors Python):
 *   running_base_kes starts at customs_value_kes.
 *   Each flat/percentage tax adds its amount to running_base_kes
 *   so subsequent stacking taxes (VAT) see the cumulative base.
 *
 *   Excise Duty is special: it only stacks on
 *   customs_value_kes + Import Duty (not all prior taxes).
 *   This is handled by passing the excise_base separately.
 *
 *   VAT stacks on running_base_kes (everything before it).
 */
function calculate_customs_taxes(frm) {
    const bank_rate   = get_bank_rate(frm);
    const weight_tons = flt(frm.doc.custom_weight) || 0;

    // ── Step 1: Import Cost Component → customs values ─────────
    const { customs_value_foreign, customs_value_kes } = _compute_customs_value(frm);

    // Set values then explicitly set the currency on each field so Frappe
    // renders the correct currency symbol in the read-only currency widget.
    // custom_custom_value  → transaction currency (frm.doc.currency)
    // custom_base_customs_value → company currency (KES)
    frm.set_value("custom_custom_value", customs_value_foreign);
    frm.set_value("custom_base_customs_value", customs_value_kes);

    // Force Frappe to re-render currency widgets with the correct symbol
    frappe.model.with_doc("Company", frm.doc.company, () => {
        const company_currency = frappe.model.get_value(
            "Company", frm.doc.company, "default_currency"
        );
        const txn_currency = frm.doc.currency || company_currency;

        // Patch the field's currency property so the widget knows which symbol to show
        if (frm.fields_dict.custom_custom_value) {
            frm.fields_dict.custom_custom_value.df.options = "currency";
            frm.fields_dict.custom_custom_value.currency = txn_currency;
        }
        if (frm.fields_dict.custom_base_customs_value) {
            frm.fields_dict.custom_base_customs_value.currency = company_currency;
        }
        if (frm.fields_dict.custom_total_taxes_kes) {
            frm.fields_dict.custom_total_taxes_kes.currency = company_currency;
        }

        frm.refresh_field("custom_custom_value");
        frm.refresh_field("custom_base_customs_value");
    });

    // ── Step 2: Customs Tax rows ────────────────────────────────
    let running_base_kes = customs_value_kes;
    let import_duty_kes  = 0;   // tracked separately for Excise base
    let total_taxes_kes  = 0;

    const tax_rows = [...(frm.doc.custom_customs_taxes || [])]
        .sort((a, b) => a.idx - b.idx);

    tax_rows.forEach(row => {
        if (!row.tax_type) return;

        const meta = _TAX_TYPE_META[row.tax_type] || {};
        let amount_kes = 0;

        if (flt(row.fixed_amount_kes) > 0 || meta.is_fixed) {
            // Fixed amount
            amount_kes = flt(row.fixed_amount_kes);

        } else if (_WEIGHT_TYPES.has(row.tax_type) || meta.is_weight_based) {
            // Weight-based: weight_tons × rate_per_ton
            amount_kes = weight_tons * flt(row.rate);

        } else if (_EXCISE_TYPES.has(row.tax_type)) {
            // Excise stacks on customs_value + import_duty only
            const excise_base = customs_value_kes + import_duty_kes;
            amount_kes = excise_base * (flt(row.rate) / 100);
            running_base_kes += amount_kes;

        } else if (_STACKING_TYPES.has(row.tax_type) || meta.is_stacking) {
            // VAT: stacks on cumulative running_base_kes
            amount_kes = running_base_kes * (flt(row.rate) / 100);
            running_base_kes += amount_kes;

        } else {
            // Flat % on raw customs value (Import Duty, IDF, RDL, …)
            amount_kes = customs_value_kes * (flt(row.rate) / 100);
            running_base_kes += amount_kes;

            // Track Import Duty for Excise base
            if ((row.tax_type || "").toLowerCase().includes("import duty") ||
                (row.tax_type || "").toLowerCase().includes("duty") &&
                !(row.tax_type || "").toLowerCase().includes("excise")) {
                import_duty_kes += amount_kes;
            }
        }

        frappe.model.set_value(row.doctype, row.name, "amount_kes", amount_kes);
        frappe.model.set_value(row.doctype, row.name, "tax_amount_kes", amount_kes);

        total_taxes_kes += amount_kes;
    });

    frm.set_value("custom_total_taxes_kes", total_taxes_kes);

    frm.refresh_fields([
        "custom_import_cost_component",
        "custom_customs_taxes",
        "custom_base_customs_value",
        "custom_custom_value",
        "custom_total_taxes_kes",
        "items",
    ]);
}

// ============================================================
// CUSTOMS TAX ROW UI HELPERS
// ============================================================

/**
 * Fetch tax-type metadata from server, cache it, apply defaults + toggle UI.
 */
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

/**
 * Toggle read-only state on rate / fixed_amount_kes based on is_fixed flag.
 *
 * Percentage-based tax → rate editable, fixed_amount read-only
 * Fixed-amount tax     → rate read-only,  fixed_amount editable
 */
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
        setup_currency_labels(frm);

        (frm.doc.custom_import_cost_component || []).forEach(row => {
            toggle_import_cost_exchange_rate(frm, row.doctype, row.name);
        });
        (frm.doc.custom_customs_taxes || []).forEach(row => {
            toggle_customs_tax_fields(frm, row.doctype, row.name);
        });

        calculate_customs_taxes(frm);
    },

    company(frm) {
        setup_currency_labels(frm);
        calculate_customs_taxes(frm);
    },

    currency(frm) {
        setup_currency_labels(frm);
        calculate_customs_taxes(frm);
    },

    conversion_rate(frm) {
        calculate_customs_taxes(frm);
    },

    custom_weight(frm) {
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
        enforce_company_currency_exchange_rate(frm, cdt, cdn);
        toggle_import_cost_exchange_rate(frm, cdt, cdn);
        calculate_customs_taxes(frm);
    },

    exchange_rate(frm, cdt, cdn) {
        enforce_company_currency_exchange_rate(frm, cdt, cdn);
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