// ============================================================
// CGM QUOTATION CLIENT SCRIPT
// ============================================================
//
// TWO EXCHANGE RATES — this is the core design principle:
//
//   1. row.exchange_rate  (on Import Cost Component)
//      → Company-chosen rate for customs value calculation.
//      → Each FOB/Freight/Insurance row can have its OWN rate.
//
//   2. frm.doc.conversion_rate  (on the Quotation itself — bank rate)
//      → Used for ALL local charges (Quotation Items).
//      → Used to convert taxes back to transaction currency for grand total.
//
// KEBS Inspection Fee is auto-calculated:
//      MAX(0.6% of customs_value_usd, USD 300)
//      Using the bank rate (conversion_rate) because it is a local charge.
//
// MSS Levy is weight-based: weight_tons × rate_per_ton (NOT a percentage).
// VAT stacks: calculated on customs_value + Import Duty + Excise Duty.
// All other taxes are flat % on raw customs_value_kes.
// ============================================================

const KEBS_ITEM_CODE  = "Kebs Inspection Fee";
const KEBS_MIN_USD    = 300;
const KEBS_PERCENT    = 0.006; // 0.6%
const KES_CURRENCY    = "KES"; // fallback; overridden by company_currency at runtime

// Tax types whose amounts stack into the base for subsequent taxes
const STACKING_TAX_TYPES  = new Set(["VAT"]);
// Tax types calculated as weight × rate_per_ton
const WEIGHT_TAX_TYPES    = new Set(["MSS Levy"]);

// ============================================================
// CURRENCY LABEL HELPERS
// ============================================================

/**
 * Warms the Company doc into frappe.locals then re-renders ALL currency
 * field labels on the form and every child table — fully dynamic.
 * No hardcoded field names: any Currency field with options set to
 * "currency" or "Company:company:default_currency" is picked up automatically.
 */
function setup_currency_labels(frm) {
    if (!frm.doc.company) return;

    frappe.model.with_doc("Company", frm.doc.company, () => {
        const company_currency = frappe.model.get_value(
            "Company", frm.doc.company, "default_currency"
        );
        const txn_currency = frm.doc.currency;

        // ── Parent doc fields ──────────────────────────────────
        (frm.meta.fields || []).forEach(df => {
            if (df.fieldtype !== "Currency") return;
            if (_is_company_currency_field(df.options)) {
                frm.set_df_property(df.fieldname, "label",
                    _currency_label(df.label, company_currency));
            } else if (df.options === "currency") {
                frm.set_df_property(df.fieldname, "label",
                    _currency_label(df.label, txn_currency));
            }
        });

        // ── All child tables ───────────────────────────────────
        (frm.meta.fields || [])
            .filter(df => df.fieldtype === "Table")
            .forEach(table_df => {
                const child_meta = frappe.get_meta(table_df.options);
                if (!child_meta) return;
                const grid = frm.fields_dict[table_df.fieldname]?.grid;
                if (!grid) return;

                (child_meta.fields || []).forEach(df => {
                    if (df.fieldtype !== "Currency") return;
                    if (_is_company_currency_field(df.options)) {
                        grid.update_docfield_property(df.fieldname, "label",
                            _currency_label(df.label, company_currency));
                    } else if (df.options === "currency") {
                        grid.update_docfield_property(df.fieldname, "label",
                            _currency_label(df.label, txn_currency));
                    }
                });

                grid.refresh();
            });

        frm.refresh_fields();
    });
}

function _is_company_currency_field(options) {
    return options === "Company:company:default_currency"
        || options === "company_currency";
}

/** Strip existing "(XXX)" suffix and append current currency. */
function _currency_label(label, currency) {
    if (!currency) return label;
    return label.replace(/ \(.*?\)$/, "") + ` (${currency})`;
}

// ============================================================
// EXCHANGE RATE HELPERS
// ============================================================

/** Bank rate — used for local charges and grand total conversion. */
function get_bank_rate(frm) {
    return flt(frm.doc.conversion_rate) || 1;
}

/**
 * Customs rate for a specific Import Cost Component row.
 * Falls back to bank rate if not set.
 */
function get_customs_rate(frm, row) {
    return flt(row.exchange_rate) || get_bank_rate(frm);
}

/** KES per USD — from first USD import cost row, else bank rate. */
function get_usd_to_kes_rate(frm) {
    for (const row of frm.doc.custom_import_cost_component || []) {
        if (row.currency === "USD" && flt(row.exchange_rate)) {
            return flt(row.exchange_rate);
        }
    }
    return get_bank_rate(frm);
}

// ============================================================
// IMPORT COST COMPONENT HELPERS
// ============================================================

/**
 * Lock exchange_rate to 1 and make read-only when the row currency
 * matches the company currency — no conversion needed.
 */
function enforce_kes_exchange_rate(frm, cdt, cdn) {
    frappe.model.with_doc("Company", frm.doc.company, () => {
        const company_currency = frappe.model.get_value(
            "Company", frm.doc.company, "default_currency"
        );
        const row = locals[cdt][cdn];
        const is_kes = row.currency === company_currency;

        if (is_kes) {
            frappe.model.set_value(cdt, cdn, "exchange_rate", 1);
        }

        frm.fields_dict.custom_import_cost_component?.grid
            .update_docfield_property("exchange_rate", "read_only", is_kes ? 1 : 0);
    });
}

/** Show exchange_rate column only when a conversion is actually needed. */
function toggle_import_cost_exchange_rate(frm, cdt, cdn) {
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
// KEBS AUTO-CALCULATION
// ============================================================

/**
 * KEBS Inspection Fee = MAX(0.6% of customs_value_usd, USD 300)
 * This is a local charge → uses bank rate (conversion_rate) for KES conversion.
 * Updates the matching Quotation Item row directly.
 */
function recalculate_kebs(frm, customs_value_usd) {
    const kebs_usd = Math.max(
        flt(customs_value_usd) * KEBS_PERCENT,
        KEBS_MIN_USD
    );
    const bank_rate = get_bank_rate(frm);

    (frm.doc.items || []).forEach(item => {
        if (item.item_code !== KEBS_ITEM_CODE) return;

        frappe.model.set_value(item.doctype, item.name, "rate", kebs_usd);
        frappe.model.set_value(item.doctype, item.name, "amount", kebs_usd * flt(item.qty || 1));
        frappe.model.set_value(item.doctype, item.name, "base_rate", kebs_usd * bank_rate);
        frappe.model.set_value(item.doctype, item.name, "base_amount", kebs_usd * bank_rate * flt(item.qty || 1));
    });

    frm.refresh_field("items");
}

// ============================================================
// CUSTOMS TAX CALCULATION (client-side preview)
// ============================================================

/**
 * Full recalculation — mirrors the Python logic exactly so the user
 * sees live results before saving.
 *
 * Tax order matters:
 *   Flat taxes (Import Duty, Excise, IDF, RDL) → on raw customs_value_kes
 *   Weight taxes (MSS Levy) → weight_tons × rate_per_ton
 *   Stacking taxes (VAT) → on (customs_value_kes + all prior duties)
 *
 * TWO rates used here:
 *   - row.exchange_rate (customs rate, company chosen) for import cost rows
 *   - frm.doc.conversion_rate (bank rate) for local charges
 */
function calculate_customs_taxes(frm) {
    const bank_rate      = get_bank_rate(frm);
    const usd_to_kes     = get_usd_to_kes_rate(frm);
    const weight_tons    = flt(frm.doc.custom_weight) || 0;

    // ── Step 1: Sum import cost rows → customs value ───────────
    let customs_value_kes = 0;
    let customs_value_usd = 0;

    (frm.doc.custom_import_cost_component || []).forEach(row => {
        const rate     = get_customs_rate(frm, row);  // company-chosen rate
        const kes      = flt(row.amount) * rate;

        frappe.model.set_value(row.doctype, row.name, "amount_kes", kes);
        customs_value_kes += kes;
        customs_value_usd += usd_to_kes ? (kes / usd_to_kes) : 0;
    });

    frm.set_value("custom_base_customs_value", customs_value_kes);
    frm.set_value("custom_custom_value", customs_value_usd);

    // ── Step 2: KEBS auto-calc (local charge, uses bank rate) ──
    recalculate_kebs(frm, customs_value_usd);

    // ── Step 3: Customs taxes ───────────────────────────────────
    let running_base_kes = customs_value_kes; // grows as stacking taxes apply
    let total_taxes_kes  = 0;
    let total_taxes_usd  = 0;

    // Sort by idx to ensure correct stacking order
    const tax_rows = [...(frm.doc.custom_customs_taxes || [])]
        .sort((a, b) => a.idx - b.idx);

    tax_rows.forEach(row => {
        if (!row.tax_type) return;

        let amount_kes = 0;

        if (flt(row.fixed_amount_kes) > 0) {
            // Fixed amount (e.g. set directly on the row)
            amount_kes = flt(row.fixed_amount_kes);

        } else if (WEIGHT_TAX_TYPES.has(row.tax_type)) {
            // MSS Levy: weight_tons × rate_per_ton (rate field = KES per ton)
            amount_kes = weight_tons * flt(row.rate);

        } else if (STACKING_TAX_TYPES.has(row.tax_type)) {
            // VAT: on customs_value + all prior duties
            amount_kes = running_base_kes * (flt(row.rate) / 100);
            running_base_kes += amount_kes; // grow base for any tax after VAT

        } else {
            // Flat % on raw customs value (Import Duty, Excise, IDF, RDL)
            amount_kes = customs_value_kes * (flt(row.rate) / 100);
            running_base_kes += amount_kes; // duties also grow base for VAT
        }

        const amount_usd = usd_to_kes ? (amount_kes / usd_to_kes) : 0;

        frappe.model.set_value(row.doctype, row.name, "amount_kes", amount_kes);
        frappe.model.set_value(row.doctype, row.name, "amount_usd", amount_usd);
        // keep legacy field in sync if it exists
        frappe.model.set_value(row.doctype, row.name, "tax_amount_kes", amount_kes);

        total_taxes_kes += amount_kes;
        total_taxes_usd += amount_usd;
    });

    frm.set_value("custom_total_taxes_kes", total_taxes_kes);
    if (frm.fields_dict.custom_total_taxes_usd) {
        frm.set_value("custom_total_taxes_usd", total_taxes_usd);
    }

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
 * Fetch tax type metadata from server and apply defaults + toggle UI.
 * Dynamically sets rate label to "Rate per Ton (KES)" for weight-based taxes.
 */
function apply_customs_tax_defaults(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.tax_type) return;

    frappe.call({
        method: "your_app.overrides.cgm_quotation.get_customs_tax_type_info",
        args: { tax_type: row.tax_type },
        callback(r) {
            if (!r.message) return;
            const info = r.message;

            if (info.default_rate != null) {
                frappe.model.set_value(cdt, cdn, "rate", info.default_rate);
            }

            // Update rate field label dynamically
            const grid = frm.fields_dict.custom_customs_taxes?.grid;
            if (grid) {
                grid.update_docfield_property("rate", "label",
                    info.is_weight_based ? "Rate per Ton (KES)" : "Rate (%)");
                grid.update_docfield_property("rate", "hidden", info.show_rate ? 0 : 1);
                grid.update_docfield_property("fixed_amount_kes", "hidden",
                    info.show_fixed_amount ? 0 : 1);
                grid.refresh();
            }

            frappe.model.set_value(cdt, cdn, "is_fixed_amount", info.is_fixed ? 1 : 0);
            calculate_customs_taxes(frm);
        },
    });
}

function toggle_customs_tax_fields(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const is_fixed = flt(row.is_fixed_amount) === 1;
    const grid = frm.fields_dict.custom_customs_taxes?.grid;
    if (!grid) return;

    grid.update_docfield_property("rate", "hidden", is_fixed ? 1 : 0);
    grid.update_docfield_property("fixed_amount_kes", "hidden", is_fixed ? 0 : 1);
    grid.refresh();
}

// ============================================================
// QUOTATION FORM EVENTS
// ============================================================

frappe.ui.form.on("Quotation", {
    refresh(frm) {
        // Warm company cache → renders all currency labels
        setup_currency_labels(frm);

        // Apply per-row UI state to existing rows
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
        // Transaction currency changed → relabel + note that bank rate may need update
        setup_currency_labels(frm);
        calculate_customs_taxes(frm);
    },

    conversion_rate(frm) {
        // Bank rate changed → affects local charges KES values and KEBS
        calculate_customs_taxes(frm);
    },

    custom_weight(frm) {
        // Weight changed → MSS Levy recalculates
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
        // This is the COMPANY-CHOSEN customs rate — not the bank rate
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

// ============================================================
// CUSTOMS TAX COMPONENT CHILD TABLE EVENTS
// ============================================================

frappe.ui.form.on("Customs Tax Component", {
    tax_type(frm, cdt, cdn) {
        // Fetches defaults from server + toggles UI fields dynamically
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