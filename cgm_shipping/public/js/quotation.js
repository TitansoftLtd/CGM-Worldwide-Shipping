// =============================================================================
// CGM QUOTATION & SALES ORDER — CLIENT SCRIPT
// =============================================================================
//
// Tax-type classification mirrors the Python constants.
// Add new type names here; no other JS changes are required.
//
// STACKING  — VAT, etc.   (stacks on the running cumulative base)
// EXCISE    — Excise Duty (stacks on customs_value + import_duty only)
// WEIGHT    — MSS Levy    (rate is KES-per-ton, not a percentage)
// Everything else: flat % applied directly to raw customs_value_kes.

const CGM = (() => {

    // ── Tax-type classification sets ─────────────────────────────────────────
    const STACKING_TYPES = new Set(["VAT"]);
    const EXCISE_TYPES   = new Set(["Excise Duty"]);
    const WEIGHT_TYPES   = new Set(["MSS Levy"]);

    // Server-fetched metadata cache  { [tax_type]: info }
    const TAX_TYPE_META = {};

    // ── Exchange-rate helpers ─────────────────────────────────────────────────

    function bankRate(frm) {
        return flt(frm.doc.conversion_rate) || 1;
    }

    function customsRate(frm, row) {
        return flt(row.exchange_rate) || bankRate(frm);
    }

    function companyCurrency(frm) {
        if (frm.cscript?.get_company_currency) return frm.cscript.get_company_currency();
        return frappe.defaults.get_default("currency");
    }

    // ── Import Cost Component helpers ─────────────────────────────────────────

    /**
     * Sum import-cost rows and return
     * { customs_value_foreign, customs_value_kes }.
     * Also updates each row's amount_kes in place.
     */
    function computeCustomsValue(frm) {
        let foreign = 0, kes = 0;
        for (const row of frm.doc.custom_import_cost_component || []) {
            const rate    = customsRate(frm, row);
            row.amount_kes = flt(row.amount) * rate;
            foreign       += flt(row.amount);
            kes           += row.amount_kes;
        }
        return { customs_value_foreign: foreign, customs_value_kes: kes };
    }

    /** Force exchange_rate = 1 when quoting in company currency. */
    function enforceExchangeRate(frm, cdt, cdn) {
        if (!frm.doc.company) return;
        frappe.model.with_doc("Company", frm.doc.company, () => {
            const co_cur       = frappe.model.get_value("Company", frm.doc.company, "default_currency");
            const is_co_cur    = frm.doc.currency === co_cur;
            const row          = locals[cdt][cdn];
            const grid         = frm.fields_dict.custom_import_cost_component?.grid;

            if (is_co_cur && flt(row?.exchange_rate) !== 1) {
                frappe.model.set_value(cdt, cdn, "exchange_rate", 1, "Float", true);
            }
            grid?.update_docfield_property("exchange_rate", "read_only", is_co_cur ? 1 : 0);
        });
    }

    /** Show / hide the exchange_rate column based on document currency. */
    function toggleImportCostExchangeRate(frm, cdt, cdn) {
        if (!frm.doc.company) return;
        frappe.model.with_doc("Company", frm.doc.company, () => {
            const co_cur  = frappe.model.get_value("Company", frm.doc.company, "default_currency");
            const needs   = frm.doc.currency && frm.doc.currency !== co_cur ? 1 : 0;
            const row     = locals[cdt][cdn];
            if (row && flt(row.show_exchange_rate) !== needs) {
                frappe.model.set_value(cdt, cdn, "show_exchange_rate", needs, "Check", true);
            }
        });
    }

    // ── Grand-total helpers ───────────────────────────────────────────────────

    function customsTaxInDocCurrency(frm) {
        const kes  = flt(frm.doc.custom_total_tax);
        const co_c = companyCurrency(frm);
        if (frm.doc.currency === co_c) return kes;
        const rate = bankRate(frm);
        return rate ? flt(kes / rate) : 0;
    }

    function updateGrandTotals(frm, opts = {}) {
        const customs_kes = flt(frm.doc.custom_total_tax);
        const customs_doc = customsTaxInDocCurrency(frm);

        frm.doc.base_grand_total = flt(frm.doc.base_total) + customs_kes;
        frm.doc.grand_total      = flt(frm.doc.total)      + customs_doc;

        if (frm.doc.disable_rounded_total) {
            frm.doc.rounded_total           = 0;
            frm.doc.base_rounded_total      = 0;
            frm.doc.rounding_adjustment     = 0;
            frm.doc.base_rounding_adjustment = 0;
        } else {
            const rp  = frappe.meta.get_field_precision(
                frappe.meta.get_docfield(frm.doc.doctype, "rounded_total"), frm.doc);
            const brp = frappe.meta.get_field_precision(
                frappe.meta.get_docfield(frm.doc.doctype, "base_rounded_total"), frm.doc);

            frm.doc.rounded_total = round_based_on_smallest_currency_fraction(
                frm.doc.grand_total, frm.doc.currency, rp);
            frm.doc.rounding_adjustment = flt(frm.doc.rounded_total - frm.doc.grand_total);

            frm.doc.base_rounded_total = round_based_on_smallest_currency_fraction(
                frm.doc.base_grand_total, companyCurrency(frm), brp);
            frm.doc.base_rounding_adjustment = flt(
                frm.doc.base_rounded_total - frm.doc.base_grand_total);
        }

        frm.refresh_fields([
            "grand_total", "base_grand_total",
            "rounded_total", "base_rounded_total",
            "rounding_adjustment", "base_rounding_adjustment",
        ]);

        updateTotalInWords(frm, opts);
    }

    function updateTotalInWords(frm, opts = {}) {
        if (!frm.doc.company || !frm.doc.currency) {
            if (opts.quiet) scheduleCleanRestore(frm);
            return;
        }
        frappe.call({
            method: "cgm_shipping.cgm_worldwide_shipping.customizations.quotation.get_total_in_words",
            args: {
                grand_total          : frm.doc.grand_total,
                rounded_total        : frm.doc.rounded_total,
                base_grand_total     : frm.doc.base_grand_total,
                base_rounded_total   : frm.doc.base_rounded_total,
                currency             : frm.doc.currency,
                company              : frm.doc.company,
                disable_rounded_total: frm.doc.disable_rounded_total,
            },
            callback(r) {
                if (r.message) {
                    frm.doc.in_words      = r.message.in_words;
                    frm.doc.base_in_words = r.message.base_in_words;
                    frm.refresh_fields(["in_words", "base_in_words"]);
                }
                if (opts.quiet) scheduleCleanRestore(frm);
            },
        });
    }

    /** Re-run ERPNext's own totals first, then apply customs on top. */
    function syncGrandTotalsAfterERPNext(frm) {
        const result = frm.cscript?.calculate_taxes_and_totals?.();
        if (result?.then) {
            result.then(() => updateGrandTotals(frm));
        } else {
            updateGrandTotals(frm);
        }
    }

    // ── "Quiet" (no-dirty-flag) helpers ──────────────────────────────────────

    function scheduleCleanRestore(frm) {
        if (!frm._cgm_keep_clean_after_sync) return;
        clearTimeout(frm._cgm_clean_restore_timer);
        frm._cgm_clean_restore_timer = setTimeout(
            () => frappe.after_ajax(() => restoreCleanState(frm)),
            250
        );
    }

    function restoreCleanState(frm) {
        if (!frm._cgm_keep_clean_after_sync) return;
        frm.doc.__unsaved = 0;
        delete frm._cgm_keep_clean_after_sync;
        frm.toolbar?.show_title_as_dirty();
        frm.toolbar?.set_primary_action(true);
    }

    // ── Customs Tax calculation ───────────────────────────────────────────────

    function isWeightBasedTax(row, meta = {}) {
        return WEIGHT_TYPES.has(row.tax_type) || Boolean(meta.is_weight_based);
    }

    /** MSS Levy and other per-weight taxes: Amount = Rate × custom_weight */
    function calculateWeightBasedTaxAmount(frm, row) {
        return flt(frm.doc.custom_weight) * flt(row.rate);
    }

    function calculateRowTaxAmount(frm, row, meta, ctx) {
        if (!row.tax_type) return 0;

        if (isWeightBasedTax(row, meta)) {
            return calculateWeightBasedTaxAmount(frm, row);
        }

        const is_fixed = flt(row.fixed_amount_kes) > 0 || Boolean(meta.is_fixed);
        if (is_fixed) {
            return flt(row.fixed_amount_kes);
        }

        const { customs_value_kes, running_base, import_duty_kes } = ctx;

        if (EXCISE_TYPES.has(row.tax_type) || meta.is_excise) {
            return (customs_value_kes + import_duty_kes) * (flt(row.rate) / 100);
        }

        if (STACKING_TYPES.has(row.tax_type) || meta.is_stacking) {
            return running_base * (flt(row.rate) / 100);
        }

        return customs_value_kes * (flt(row.rate) / 100);
    }

    /**
     * Main recalculation entry point.
     * Replicates the Python logic so the form shows live previews.
     */
    function calculateCustomsTaxes(frm, opts = {}) {
        if (opts.quiet) frm._cgm_keep_clean_after_sync = true;

        const { customs_value_foreign, customs_value_kes } = computeCustomsValue(frm);

        frm.doc.custom_custom_value = customs_value_foreign;
        frm.doc.custom_base_customs_value = customs_value_kes;

        let running_base    = customs_value_kes;
        let import_duty_kes = 0;
        let total_taxes_kes = 0;

        const rows = [...(frm.doc.custom_customs_taxes || [])].sort((a, b) => a.idx - b.idx);

        for (const row of rows) {
            if (!row.tax_type) continue;

            const meta = TAX_TYPE_META[row.tax_type] || {};
            const ctx  = { customs_value_kes, running_base, import_duty_kes };
            const amount = calculateRowTaxAmount(frm, row, meta, ctx);

            row.amount_kes     = amount;
            row.tax_amount_kes = amount;
            total_taxes_kes   += amount;

            if (!isWeightBasedTax(row, meta)) {
                running_base    += amount;
                if (!EXCISE_TYPES.has(row.tax_type) && !meta.is_excise
                    && !STACKING_TYPES.has(row.tax_type) && !meta.is_stacking) {
                    import_duty_kes += amount;
                }
            }
        }

        frm.doc.custom_total_tax = total_taxes_kes;
        updateGrandTotals(frm, opts);

        frm.refresh_fields([
            "custom_import_cost_component",
            "custom_custom_value",
            "custom_base_customs_value",
            "custom_customs_taxes",
            "custom_total_tax",
        ]);

        calculateItemPricing(frm, opts);
    }

    // ── Item pricing engine (Item.custom_item_pricing_rules) ─────────────────

    const CALCULATION_PERCENTAGE = "Percentage";
    const CALCULATION_FIXED = "Fixed";
    const RULE_TYPE_FIXED = "Fixed Rate";
    const ITEM_PRICING_RULES = {};

    function invalidateItemPricingRule(item_code) {
        if (item_code) delete ITEM_PRICING_RULES[item_code];
    }

    function calculateRuleAmount(custom_value, rule, frm) {
        const calculation_type = rule.calculation_type || CALCULATION_PERCENTAGE;
        const quotation_currency = frm.doc.currency;
        const company_currency = companyCurrency(frm);
        const exchange_rate = bankRate(frm);

        if (calculation_type === CALCULATION_FIXED) {
            const fixed_rate = flt(rule.fixed_rate);
            const rule_currency = rule.currency;

            if (rule_currency === quotation_currency) return fixed_rate;
            if (rule_currency === company_currency) {
                return exchange_rate ? flt(fixed_rate / exchange_rate) : 0;
            }
            return 0;
        }

        return (flt(rule.percentage_rate) / 100) * flt(custom_value);
    }

    function ruleTypeLabel(calculation_type) {
        return calculation_type === CALCULATION_FIXED ? RULE_TYPE_FIXED : CALCULATION_PERCENTAGE;
    }

    function calculateItemPricingForItem(custom_value, rules, frm) {
        if (!rules?.length) return null;

        let winning_rule = null;
        let winning_amount = 0;

        for (const rule of rules) {
            const amount = calculateRuleAmount(custom_value, rule, frm);
            if (amount > winning_amount) {
                winning_amount = amount;
                winning_rule = rule;
            }
        }

        if (!winning_rule) return null;

        return {
            audit_row: {
                rule_type: ruleTypeLabel(winning_rule.calculation_type),
                percentage_rate: flt(winning_rule.percentage_rate),
                fixed_rate: flt(winning_rule.fixed_rate),
                rule_currency: winning_rule.currency,
                exchange_rate_used: bankRate(frm),
                calculated_amount: winning_amount,
                final_applied_rate: winning_amount,
            },
            item_rate: winning_amount,
        };
    }

    function calculateItemPricingLocal(frm, rules, opts = {}) {
        const custom_value = flt(frm.doc.custom_custom_value);
        const pricing_rows = [];
        const item_updates = [];

        for (const item of frm.doc.items || []) {
            if (!item.item_code) continue;

            const item_rules = rules[item.item_code];
            if (!item_rules?.length) continue;

            const result = calculateItemPricingForItem(custom_value, item_rules, frm);
            if (!result) continue;

            pricing_rows.push({ item: item.item_code, ...result.audit_row });
            item_updates.push({
                name: item.name,
                item_code: item.item_code,
                rate: result.item_rate,
            });
        }

        applyItemPricingResult(frm, { pricing_rows, item_updates }, opts);
    }

    function applyItemPricingResult(frm, result, opts = {}) {
        if (!frm.fields_dict.custom_item_pricing) return;

        frm.clear_table("custom_item_pricing");
        for (const row of result.pricing_rows || []) {
            frm.add_child("custom_item_pricing", row);
        }
        frm.refresh_field("custom_item_pricing");

        const updates = result.item_updates || [];
        if (!updates.length) {
            if (opts.quiet) scheduleCleanRestore(frm);
            return;
        }

        const pending = updates.map((upd) => {
            const item = (frm.doc.items || []).find((row) => row.name === upd.name);
            if (!item) return Promise.resolve();
            return frappe.model.set_value(item.doctype, item.name, "rate", upd.rate);
        });

        Promise.all(pending).then(() => {
            CGM.syncGrandTotalsAfterERPNext(frm);
            if (opts.quiet) scheduleCleanRestore(frm);
        });
    }

    function calculateItemPricing(frm, opts = {}) {
        if (!frm.fields_dict.custom_item_pricing) {
            if (opts.quiet) scheduleCleanRestore(frm);
            return;
        }
        if (!frm.doc.company || !frm.doc.currency) {
            if (opts.quiet) scheduleCleanRestore(frm);
            return;
        }

        if (opts.quiet) frm._cgm_keep_clean_after_sync = true;

        const item_codes = [
            ...new Set((frm.doc.items || []).map((row) => row.item_code).filter(Boolean)),
        ];
        if (!item_codes.length) {
            applyItemPricingResult(frm, { pricing_rows: [], item_updates: [] }, opts);
            return;
        }

        const missing = item_codes.filter((code) => !(code in ITEM_PRICING_RULES));
        if (missing.length) {
            frappe.call({
                method: "cgm_shipping.cgm_worldwide_shipping.customizations.item_pricing.get_item_pricing_rules",
                args: { item_codes },
                callback(r) {
                    Object.assign(ITEM_PRICING_RULES, r.message || {});
                    for (const code of item_codes) {
                        if (!ITEM_PRICING_RULES[code]) ITEM_PRICING_RULES[code] = [];
                    }
                    calculateItemPricingLocal(frm, ITEM_PRICING_RULES, opts);
                },
            });
            return;
        }

        calculateItemPricingLocal(frm, ITEM_PRICING_RULES, opts);
    }

    // ── Customs Tax row UI helpers ────────────────────────────────────────────

    function applyCustomsTaxDefaults(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.tax_type) return;

        if (TAX_TYPE_META[row.tax_type]) {
            applyMetaToRow(frm, cdt, cdn, TAX_TYPE_META[row.tax_type]);
            return;
        }

        frappe.call({
            method: "cgm_shipping.cgm_worldwide_shipping.customizations.quotation.get_customs_tax_type_info",
            args: { tax_type: row.tax_type },
            callback(r) {
                if (!r.message) return;
                TAX_TYPE_META[row.tax_type] = r.message;
                applyMetaToRow(frm, cdt, cdn, r.message);
            },
        });
    }

    function applyMetaToRow(frm, cdt, cdn, info) {
        if (info.default_rate != null) {
            frappe.model.set_value(cdt, cdn, "rate", info.default_rate);
        }
        if (!info.is_weight_based) {
            frappe.model.set_value(cdt, cdn, "is_fixed_amount", info.is_fixed ? 1 : 0);
        }

        const grid = frm.fields_dict.custom_customs_taxes?.grid;
        if (grid) {
            grid.update_docfield_property("rate",             "label",     info.rate_label || "Rate (%)");
            grid.update_docfield_property("rate",             "hidden",    info.show_rate ? 0 : 1);
            grid.update_docfield_property("fixed_amount_kes", "hidden",    info.show_fixed_amount ? 0 : 1);
            grid.update_docfield_property("rate",             "read_only", info.is_fixed ? 1 : 0);
            grid.update_docfield_property("fixed_amount_kes", "read_only", info.is_fixed ? 0 : 1);
            grid.refresh();
        }

        calculateCustomsTaxes(frm);
    }

    function toggleCustomsTaxFields(frm, cdt, cdn) {
        const row      = locals[cdt][cdn];
        const is_fixed = flt(row?.is_fixed_amount) === 1;
        const grid     = frm.fields_dict.custom_customs_taxes?.grid;
        if (!grid) return;

        grid.update_docfield_property("rate",             "hidden",    is_fixed ? 1 : 0);
        grid.update_docfield_property("fixed_amount_kes", "hidden",    is_fixed ? 0 : 1);
        grid.update_docfield_property("rate",             "read_only", is_fixed ? 1 : 0);
        grid.update_docfield_property("fixed_amount_kes", "read_only", is_fixed ? 0 : 1);
    }

    // ── Grid setup on load ────────────────────────────────────────────────────

    function setupCustomsTaxGridUI(frm) {
        for (const row of frm.doc.custom_customs_taxes || []) {
            toggleCustomsTaxFields(frm, row.doctype, row.name);
        }
        frm.fields_dict.custom_customs_taxes?.grid?.refresh();
    }

    function setupImportCostGridUI(frm) {
        for (const row of frm.doc.custom_import_cost_component || []) {
            toggleImportCostExchangeRate(frm, row.doctype, row.name);
        }
    }

    function setupItemPricingGridUI(frm) {
        if (!frm.fields_dict.custom_item_pricing) return;

        frm.set_df_property("custom_item_pricing", "read_only", 0);
        frm.set_df_property("custom_item_pricing", "cannot_add_rows", 1);
        frm.fields_dict.custom_item_pricing.grid?.refresh();

        const items_grid = frm.fields_dict.items?.grid;
        if (items_grid) {
            items_grid.update_docfield_property("rate", "read_only", 1);
            items_grid.refresh();
        }
    }

    function seedImportCostExchangeRate(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row || flt(row.exchange_rate)) return;
        if (!frm.doc.currency || frm.doc.currency === companyCurrency(frm)) return;
        frappe.model.set_value(cdt, cdn, "exchange_rate", bankRate(frm), "Float", true);
    }

    // ── Public API ────────────────────────────────────────────────────────────
    return {
        calculateCustomsTaxes,
        calculateItemPricing,
        invalidateItemPricingRule,
        updateTotalInWords,
        syncGrandTotalsAfterERPNext,
        setupCustomsTaxGridUI,
        setupImportCostGridUI,
        setupItemPricingGridUI,
        applyCustomsTaxDefaults,
        toggleCustomsTaxFields,
        enforceExchangeRate,
        toggleImportCostExchangeRate,
        seedImportCostExchangeRate,
    };
})();


// =============================================================================
// QUOTATION FORM EVENTS
// =============================================================================

const CGM_QUOTATION_BILLING_STATES = new Set(["Approved", "Shared with Client"]);

frappe.ui.form.on("Quotation", {
    recalculate_import_costs(frm) {
        CGM.calculateCustomsTaxes(frm);
    },

    refresh(frm) {
        CGM.setupImportCostGridUI(frm);
        CGM.setupCustomsTaxGridUI(frm);
        CGM.setupItemPricingGridUI(frm);
        CGM.add_sales_invoice_button(frm);

        // Submitted quotations already have server-calculated totals.
        // Re-running client math only rewrites frm.doc and falsely marks the form dirty.
        if (frm.doc.docstatus === 1 && !frm.is_dirty()) return;

        CGM.calculateCustomsTaxes(frm, { quiet: !frm.is_dirty() });
    },

    after_save(frm) {
        frm.doc.__unsaved = 0;
        frm.toolbar?.show_title_as_dirty();
        frm.toolbar?.set_primary_action(true);
    },

    company(frm)         { CGM.calculateCustomsTaxes(frm); },
    currency(frm)        { CGM.calculateCustomsTaxes(frm); },
    conversion_rate(frm) { CGM.calculateCustomsTaxes(frm); },
    custom_weight(frm)   { CGM.calculateCustomsTaxes(frm); },
    opportunity(frm)     { CGM.fetch_shipment_references(frm); },
    custom_shipment(frm) { CGM.fetch_shipment_references(frm); },

    custom_import_cost_component_add(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_import_cost_component_remove(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_customs_taxes_add(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_customs_taxes_remove(frm) {
        frm.trigger("recalculate_import_costs");
    },

    items_add(frm) {
        CGM.calculateCustomsTaxes(frm);
    },
    items_remove(frm) {
        CGM.calculateCustomsTaxes(frm);
    },

    grand_total(frm) {
        CGM.updateTotalInWords(frm);
    },
    rounded_total(frm) {
        CGM.updateTotalInWords(frm);
    },
    base_grand_total(frm) {
        CGM.updateTotalInWords(frm);
    },
    base_rounded_total(frm) {
        CGM.updateTotalInWords(frm);
    },
    disable_rounded_total(frm) {
        CGM.updateTotalInWords(frm);
    },
});

CGM.add_sales_invoice_button = function (frm) {
    if (frm.doc.docstatus !== 1) return;
    if (!CGM_QUOTATION_BILLING_STATES.has(frm.doc.workflow_state)) return;
    if (!frappe.model.can_create("Sales Invoice")) return;
    if (["Lost", "Ordered"].includes(frm.doc.status)) return;

    frm.add_custom_button(__("Sales Invoice"), () => {
        const has_alternative_item = (frm.doc.items || []).some((item) => item.is_alternative);
        if (has_alternative_item) {
            frappe.msgprint(__("Please create a Sales Invoice from a Sales Order when alternative items are used."));
            return;
        }
        frappe.model.open_mapped_doc({
            method: "erpnext.selling.doctype.quotation.quotation.make_sales_invoice",
            frm,
        });
    }, __("Create"));
};

CGM.fetch_shipment_references = function (frm) {
    const fields = [
        ["custom_coo", "custom_country_of_origin"],
        ["custom_idfno", "custom_idf_number"],
        ["custom_client_ref_no", "custom_client_ref_no"],
        ["custom_our_ref_no", "custom_cgm_ref_no"],
    ];

    const apply_project = (project) => {
        if (!project) return;
        for (const [target, source] of fields) {
            if (!frm.doc[target] && project[source]) {
                frm.set_value(target, project[source]);
            }
        }
    };

    if (frm.doc.custom_shipment) {
        frappe.db.get_doc("Project", frm.doc.custom_shipment).then(apply_project);
        return;
    }

    if (!frm.doc.opportunity) return;

    frappe.db.get_value("Opportunity", frm.doc.opportunity, "custom_country_of_origin").then((r) => {
        if (!frm.doc.custom_coo && r.message?.custom_country_of_origin) {
            frm.set_value("custom_coo", r.message.custom_country_of_origin);
        }
    });
};

frappe.ui.form.on("Quotation Item", {
    item_code(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        CGM.invalidateItemPricingRule(row?.item_code);
        CGM.calculateCustomsTaxes(frm);
    },
    rate(frm)         { CGM.calculateCustomsTaxes(frm); },
    qty(frm)          { CGM.calculateCustomsTaxes(frm); },
    amount(frm)       { CGM.calculateCustomsTaxes(frm); },
});


// =============================================================================
// SALES ORDER FORM EVENTS
// (same logic — customs tables copied from Quotation by make_sales_order)
// =============================================================================

frappe.ui.form.on("Sales Order", {
    recalculate_import_costs(frm) {
        CGM.calculateCustomsTaxes(frm);
    },

    refresh(frm) {
        CGM.setupImportCostGridUI(frm);
        CGM.setupCustomsTaxGridUI(frm);
        CGM.setupItemPricingGridUI(frm);

        if (frm.doc.docstatus === 1 && !frm.is_dirty()) return;

        CGM.calculateCustomsTaxes(frm, { quiet: !frm.is_dirty() });
    },

    company(frm)         { CGM.calculateCustomsTaxes(frm); },
    currency(frm)        { CGM.calculateCustomsTaxes(frm); },
    conversion_rate(frm) { CGM.calculateCustomsTaxes(frm); },
    custom_weight(frm)   { CGM.calculateCustomsTaxes(frm); },

    custom_import_cost_component_add(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_import_cost_component_remove(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_customs_taxes_add(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_customs_taxes_remove(frm) {
        frm.trigger("recalculate_import_costs");
    },

    items_add(frm) {
        CGM.calculateCustomsTaxes(frm);
    },
    items_remove(frm) {
        CGM.calculateCustomsTaxes(frm);
    },
});

frappe.ui.form.on("Sales Order Item", {
    item_code(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        CGM.invalidateItemPricingRule(row?.item_code);
        CGM.calculateCustomsTaxes(frm);
    },
    rate(frm)         { CGM.calculateCustomsTaxes(frm); },
    qty(frm)          { CGM.calculateCustomsTaxes(frm); },
    amount(frm)       { CGM.calculateCustomsTaxes(frm); },
});


frappe.ui.form.on("Import Cost Component", {
    custom_import_cost_component_add(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_import_cost_component_remove(frm) {
        frm.trigger("recalculate_import_costs");
    },

    amount(frm) {
        frm.trigger("recalculate_import_costs");
    },
    exchange_rate(frm) {
        frm.trigger("recalculate_import_costs");
    },
    charge_item(frm) {
        frm.trigger("recalculate_import_costs");
    },

    form_render(frm, cdt, cdn) {
        CGM.enforceExchangeRate(frm, cdt, cdn);
        CGM.toggleImportCostExchangeRate(frm, cdt, cdn);
        CGM.seedImportCostExchangeRate(frm, cdt, cdn);
        frm.trigger("recalculate_import_costs");
    },
});

// Customs Tax Component
frappe.ui.form.on("Customs Tax Component", {
    tax_type(frm, cdt, cdn) {
        CGM.applyCustomsTaxDefaults(frm, cdt, cdn);
    },

    rate(frm, cdt, cdn) {
        CGM.calculateCustomsTaxes(frm);
    },
    fixed_amount_kes(frm) { CGM.calculateCustomsTaxes(frm); },

    is_fixed_amount(frm, cdt, cdn) {
        CGM.toggleCustomsTaxFields(frm, cdt, cdn);
        frm.fields_dict.custom_customs_taxes?.grid?.refresh();
        CGM.calculateCustomsTaxes(frm);
    },

    form_render(frm, cdt, cdn) {
        CGM.toggleCustomsTaxFields(frm, cdt, cdn);
        CGM.calculateCustomsTaxes(frm);
    },
});