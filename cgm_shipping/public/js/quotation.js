// =============================================================================
// CGM QUOTATION & SALES ORDER — CLIENT SCRIPT
// =============================================================================
//
// Customs tax behaviour is driven by Customs Tax Type master config (fetched via
// get_customs_tax_type_info). Client preview math mirrors customs_tax_calculation.py.

const CALC_MODE_PERCENTAGE = "Percentage";
const CALC_MODE_PER_UNIT = "Per Unit";
const CALC_MODE_FIXED_AMOUNT = "Fixed Amount";
const RATE_AMOUNT_COLUMN_LABEL = __("Rate / Amount");

const CGM = (() => {

    // Server-fetched metadata cache  { [tax_type]: info }
    const TAX_TYPE_META = {};
    const VOLUME_UOM_CACHE = {};
    const LEGACY_VOLUME_UOM_ABBREVS = new Set(["liter", "litre", "l", "ltr"]);

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

    function isVolumeUom(uom) {
        const normalized = (uom || "").trim();
        if (!normalized) return false;
        if (Object.prototype.hasOwnProperty.call(VOLUME_UOM_CACHE, normalized)) {
            return VOLUME_UOM_CACHE[normalized];
        }
        if (LEGACY_VOLUME_UOM_ABBREVS.has(normalized.toLowerCase())) {
            console.warn(
                `CGM: volume UOM fallback for '${normalized}'; configure UOM master.`
            );
            return true;
        }
        return false;
    }

    function refreshVolumeUomCache(frm) {
        const uom = (frm.doc.custom_uom || "").trim();
        if (!uom) {
            frm._cgm_is_volume_uom = false;
            return Promise.resolve(false);
        }
        if (Object.prototype.hasOwnProperty.call(VOLUME_UOM_CACHE, uom)) {
            frm._cgm_is_volume_uom = VOLUME_UOM_CACHE[uom];
            return Promise.resolve(VOLUME_UOM_CACHE[uom]);
        }

        return frappe.call({
            method: "cgm_shipping.cgm_worldwide_shipping.customizations.quotation.is_quotation_volume_uom",
            args: { uom },
        }).then((r) => {
            const is_volume = !!r.message;
            VOLUME_UOM_CACHE[uom] = is_volume;
            frm._cgm_is_volume_uom = is_volume;
            return is_volume;
        });
    }

    function shipmentQuantity(frm) {
        const uom = (frm.doc.custom_uom || "").trim();
        const use_volume = frm._cgm_is_volume_uom ?? isVolumeUom(uom);
        if (use_volume) {
            return flt(frm.doc.custom_volume);
        }
        return flt(frm.doc.custom_weight);
    }

    function taxTypeMetaArgs(frm, tax_type) {
        return {
            tax_type,
            quotation_uom: frm.doc.custom_uom || "",
            company: frm.doc.company || "",
        };
    }

    function prefetchTaxTypeMeta(frm) {
        const tax_types = [
            ...new Set(
                (frm.doc.custom_customs_taxes || [])
                    .map((row) => row.tax_type)
                    .filter(Boolean)
            ),
        ];

        const requests = tax_types
            .filter((tax_type) => !TAX_TYPE_META[tax_type])
            .map((tax_type) => frappe.call({
                method: "cgm_shipping.cgm_worldwide_shipping.customizations.quotation.get_customs_tax_type_info",
                args: taxTypeMetaArgs(frm, tax_type),
            }).then((r) => {
                if (r.message) {
                    TAX_TYPE_META[tax_type] = r.message;
                }
            }));

        return Promise.all(requests);
    }

    function clearTaxTypeMetaCache() {
        for (const key of Object.keys(TAX_TYPE_META)) {
            delete TAX_TYPE_META[key];
        }
    }

    function scheduleCustomsTaxRecalc(frm) {
        clearTimeout(frm._cgm_customs_tax_recalc_timer);
        // Defer until Frappe finishes grid add/remove (after_ajax never runs without a request).
        frm._cgm_customs_tax_recalc_timer = setTimeout(
            () => frm.trigger("recalculate_import_costs"),
            0
        );
    }

    function scheduleItemPricingRecalc(frm, opts = {}) {
        clearTimeout(frm._cgm_item_pricing_recalc_timer);
        frm._cgm_item_pricing_recalc_timer = setTimeout(() => {
            const recalc = () => calculateCustomsTaxes(frm, opts);
            recalc();
            // ERPNext get_item_details / apply_price_list runs async after item_code.
            frappe.after_ajax(() => setTimeout(recalc, 50));
        }, 0);
    }

    function syncCustomsTaxContext(frm, opts = {}) {
        return Promise.all([
            refreshVolumeUomCache(frm),
            prefetchTaxTypeMeta(frm),
        ]).then(() => {
            refreshCustomsTaxGridUI(frm);
            calculateCustomsTaxes(frm, opts);
        });
    }

    function resolveCalculationMode(row, meta = {}) {
        const mode = (row.calculation_mode || "").trim();
        const allowed = meta.allowed_modes || [CALC_MODE_PERCENTAGE];
        if (allowed.includes(mode)) {
            return mode;
        }
        return meta.default_calculation_mode || CALC_MODE_PERCENTAGE;
    }

    function rateLabelForMode(mode, frm, meta = {}) {
        if (meta.rate_labels && meta.rate_labels[mode]) {
            return meta.rate_labels[mode];
        }
        const currency = meta.company_currency || companyCurrency(frm);
        if (mode === CALC_MODE_PER_UNIT) {
            const uom = (frm.doc.custom_uom || __("Unit")).trim();
            return __("Rate per {0} ({1})", [uom, currency]);
        }
        if (mode === CALC_MODE_FIXED_AMOUNT) {
            return __("Fixed Amount ({0})", [currency]);
        }
        return __("Rate (%)");
    }

    function shouldFeedRunningBase(meta, mode) {
        if (meta.feeds_running_base === 0 || meta.feeds_running_base === false) {
            return false;
        }
        if (mode === CALC_MODE_PER_UNIT) {
            if (meta.per_unit_skips_running_base || meta.is_mss_levy) {
                return false;
            }
        }
        return true;
    }

    function importDutyContribution(meta, mode, amount) {
        if (meta.is_excise || meta.is_stacking) {
            return 0;
        }
        if (mode === CALC_MODE_PER_UNIT && meta.per_unit_skips_running_base) {
            return 0;
        }
        if (mode === CALC_MODE_FIXED_AMOUNT) {
            return 0;
        }
        if (meta.affects_import_duty === 0 || meta.affects_import_duty === false) {
            return 0;
        }
        return amount;
    }

    function fixedAmountForRow(row, mode) {
        if (mode !== CALC_MODE_FIXED_AMOUNT) {
            return 0;
        }
        const amount = flt(row.fixed_amount_kes) || flt(row.rate);
        if (amount) {
            row.fixed_amount_kes = amount;
            row.rate = amount;
        }
        return amount;
    }

    function syncCustomsTaxFixedAmountRow(frm, cdt, cdn) {
        const row = locals[cdt]?.[cdn];
        if (!row?.tax_type) return;

        const meta = TAX_TYPE_META[row.tax_type] || {};
        const mode = resolveCalculationMode(row, meta);
        fixedAmountForRow(row, mode);
    }

    function calculateRowTaxAmount(frm, row, meta, ctx) {
        if (!row.tax_type) return 0;

        const mode = resolveCalculationMode(row, meta);
        const rate = flt(row.rate);
        const { customs_value_kes, running_base, import_duty_kes } = ctx;

        if (mode === CALC_MODE_FIXED_AMOUNT) {
            return fixedAmountForRow(row, mode);
        }

        if (mode === CALC_MODE_PER_UNIT) {
            return shipmentQuantity(frm) * rate;
        }

        if (meta.is_excise) {
            return (customs_value_kes + import_duty_kes) * (rate / 100);
        }

        if (meta.is_stacking) {
            return running_base * (rate / 100);
        }

        return customs_value_kes * (rate / 100);
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
            const mode = resolveCalculationMode(row, meta);
            if (row.calculation_mode !== mode) {
                row.calculation_mode = mode;
            }
            if (mode === CALC_MODE_FIXED_AMOUNT) {
                fixedAmountForRow(row, mode);
            }

            const ctx  = { customs_value_kes, running_base, import_duty_kes };
            const amount = calculateRowTaxAmount(frm, row, meta, ctx);

            row.amount_kes     = amount;
            row.tax_amount_kes = amount;
            total_taxes_kes   += amount;

            if (shouldFeedRunningBase(meta, mode)) {
                running_base += amount;
                import_duty_kes += importDutyContribution(meta, mode, amount);
            }
        }

        frm.doc.custom_total_tax = total_taxes_kes;
        updateGrandTotals(frm, opts);

        frm.refresh_fields([
            "custom_import_cost_component",
            "custom_custom_value",
            "custom_base_customs_value",
        ]);
        if (frm.fields_dict.custom_total_tax) {
            frm.refresh_field("custom_total_tax");
        }
        refreshCustomsTaxAmounts(frm);

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
                rate: flt(result.audit_row.final_applied_rate),
            });
        }

        applyItemPricingResult(frm, { pricing_rows, item_updates }, opts);
    }

    function findQuotationItem(frm, upd) {
        const items = frm.doc.items || [];
        return (
            items.find((row) => row.name === upd.name && row.item_code === upd.item_code)
            || items.find((row) => row.name === upd.name)
            || items.find((row) => row.item_code === upd.item_code)
        );
    }

    function applyItemPricingRates(frm, updates) {
        if (!updates?.length) return;

        for (const upd of updates) {
            const item = findQuotationItem(frm, upd);
            if (!item) continue;

            const rate = flt(upd.rate);
            item.rate = rate;
            if (!flt(item.qty)) {
                item.qty = 1;
            }
        }

        // Recompute line amounts from our rates without fetching price-list prices.
        frappe.flags.dont_fetch_price_list_rate = true;
        try {
            if (frm.cscript?._calculate_taxes_and_totals) {
                frm.cscript._calculate_taxes_and_totals();
            } else {
                frm.cscript?.calculate_taxes_and_totals?.();
            }
        } finally {
            frappe.flags.dont_fetch_price_list_rate = false;
        }

        const grid = frm.fields_dict.items?.grid;
        if (!grid) return;

        for (const upd of updates) {
            const item = findQuotationItem(frm, upd);
            if (!item) continue;
            const grid_row = grid.grid_rows_by_docname?.[item.name];
            if (!grid_row) continue;
            grid_row.refresh_field("rate");
            grid_row.refresh_field("amount");
            grid_row.refresh_field("base_rate");
            grid_row.refresh_field("base_amount");
        }
    }

    function itemUpdatesFromPricingResult(result) {
        const updates = [...(result.item_updates || [])];
        if (updates.length) return updates;

        return (result.pricing_rows || [])
            .filter((row) => row.item && flt(row.final_applied_rate))
            .map((row) => ({
                item_code: row.item,
                rate: flt(row.final_applied_rate),
            }));
    }

    function applyItemPricingResult(frm, result, opts = {}) {
        if (!frm.fields_dict.custom_item_pricing) return;

        frm.clear_table("custom_item_pricing");
        for (const row of result.pricing_rows || []) {
            frm.add_child("custom_item_pricing", row);
        }
        frm.refresh_field("custom_item_pricing");

        const updates = itemUpdatesFromPricingResult(result);
        if (!updates.length) {
            if (opts.quiet) scheduleCleanRestore(frm);
            return;
        }

        applyItemPricingRates(frm, updates);
        updateGrandTotals(frm, opts);

        if (opts.quiet) scheduleCleanRestore(frm);
    }

    function calculateItemPricing(frm, opts = {}) {
        if (!frm.fields_dict.custom_item_pricing) {
            if (opts.quiet) scheduleCleanRestore(frm);
            return;
        }

        const item_codes = [
            ...new Set((frm.doc.items || []).map((row) => row.item_code).filter(Boolean)),
        ];

        if (!item_codes.length) {
            applyItemPricingResult(frm, { pricing_rows: [], item_updates: [] }, opts);
            return;
        }

        if (!frm.doc.company || !frm.doc.currency) {
            if (opts.quiet) scheduleCleanRestore(frm);
            return;
        }

        if (opts.quiet) frm._cgm_keep_clean_after_sync = true;

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
            args: taxTypeMetaArgs(frm, row.tax_type),
            callback(r) {
                if (!r.message) return;
                TAX_TYPE_META[row.tax_type] = r.message;
                applyMetaToRow(frm, cdt, cdn, r.message);
            },
        });
    }

    function applyMetaToRow(frm, cdt, cdn, info) {
        const row = locals[cdt][cdn];
        if (!row) return;

        if (info.default_calculation_mode) {
            frappe.model.set_value(
                cdt,
                cdn,
                "calculation_mode",
                info.default_calculation_mode,
                null,
                true
            );
        }
        if (info.default_rate != null && !flt(row.rate)) {
            frappe.model.set_value(cdt, cdn, "rate", info.default_rate, null, true);
        }

        updateCustomsTaxRowUI(frm, cdt, cdn, info);
        calculateCustomsTaxes(frm);
    }

    function refreshCustomsTaxAmounts(frm) {
        const grid = frm.fields_dict.custom_customs_taxes?.grid;
        if (!grid) return;

        for (const row of frm.doc.custom_customs_taxes || []) {
            const grid_row = grid.grid_rows_by_docname?.[row.name];
            if (!grid_row) continue;
            grid_row.refresh_field("amount_kes");
            grid_row.refresh_field("calculation_mode");
            grid_row.refresh_field("rate");
        }
    }

    function updateCustomsTaxRowUI(frm, cdt, cdn, info) {
        const row = locals[cdt][cdn];
        if (!row?.tax_type) return;

        const meta = info || TAX_TYPE_META[row.tax_type] || {};
        const mode = resolveCalculationMode(row, meta);
        const hint = rateLabelForMode(mode, frm, meta);
        const grid = frm.fields_dict.custom_customs_taxes?.grid;
        const grid_row = grid?.grid_rows_by_docname?.[cdn];
        const row_form = grid_row?.grid_form;

        if (!row_form) return;

        // Contextual hint inside the row editor only — not the grid column header.
        row_form.set_df_property(
            "rate",
            "description",
            mode === CALC_MODE_FIXED_AMOUNT ? "" : hint
        );
        row_form.set_df_property(
            "fixed_amount_kes",
            "description",
            mode === CALC_MODE_FIXED_AMOUNT ? hint : ""
        );
        row_form.set_df_property("rate", "hidden", mode === CALC_MODE_FIXED_AMOUNT ? 1 : 0);
        row_form.set_df_property("fixed_amount_kes", "hidden", mode === CALC_MODE_FIXED_AMOUNT ? 0 : 1);
    }

    function setupCustomsTaxGridHeaders(frm) {
        const grid = frm.fields_dict.custom_customs_taxes?.grid;
        if (!grid) return;

        grid.update_docfield_property("rate", "label", RATE_AMOUNT_COLUMN_LABEL);
        grid.update_docfield_property("fixed_amount_kes", "hidden", 1);

        const rate_df = (grid.docfields || []).find((df) => df.fieldname === "rate");
        if (!rate_df) return;

        rate_df.formatter = (value, _df, doc) => {
            try {
                if (doc.calculation_mode === CALC_MODE_FIXED_AMOUNT) {
                    const currency = companyCurrency(frm);
                    const fixed = flt(doc.fixed_amount_kes) || flt(doc.rate);
                    return fixed && currency ? format_currency(fixed, currency) : fixed || "";
                }
            } catch (e) {
                console.warn("CGM customs tax formatter:", e);
            }
            return value == null || value === "" ? "" : value;
        };
    }

    function refreshCustomsTaxGridUI(frm) {
        setupCustomsTaxGridHeaders(frm);
        for (const row of frm.doc.custom_customs_taxes || []) {
            if (row.tax_type) {
                updateCustomsTaxRowUI(frm, row.doctype, row.name);
            }
        }
    }

    // ── Grid setup on load ────────────────────────────────────────────────────

    function setupCustomsTaxGridUI(frm) {
        setupCustomsTaxGridHeaders(frm);
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
        updateCustomsTaxRowUI,
        syncCustomsTaxFixedAmountRow,
        refreshCustomsTaxGridUI,
        syncCustomsTaxContext,
        scheduleCustomsTaxRecalc,
        scheduleItemPricingRecalc,
        clearTaxTypeMetaCache,
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

        CGM.syncCustomsTaxContext(frm, { quiet: !frm.is_dirty() });
    },

    after_save(frm) {
        frm.doc.__unsaved = 0;
        frm.toolbar?.show_title_as_dirty();
        frm.toolbar?.set_primary_action(true);
    },

    company(frm) {
        CGM.clearTaxTypeMetaCache();
        CGM.syncCustomsTaxContext(frm);
    },
    currency(frm)        { CGM.calculateCustomsTaxes(frm); },
    conversion_rate(frm) { CGM.calculateCustomsTaxes(frm); },
    custom_weight(frm)   { CGM.calculateCustomsTaxes(frm); },
    custom_volume(frm)   { CGM.calculateCustomsTaxes(frm); },
    custom_uom(frm) {
        CGM.clearTaxTypeMetaCache();
        CGM.syncCustomsTaxContext(frm);
    },
    opportunity(frm)     { CGM.fetch_shipment_references(frm); },
    custom_shipment(frm) { CGM.fetch_shipment_references(frm); },

    custom_import_cost_component_add(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_import_cost_component_remove(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_customs_taxes_add(frm) {
        CGM.scheduleCustomsTaxRecalc(frm);
    },
    custom_customs_taxes_remove(frm) {
        CGM.scheduleCustomsTaxRecalc(frm);
    },

    items_add(frm) {
        CGM.scheduleItemPricingRecalc(frm);
    },
    items_remove(frm) {
        CGM.scheduleItemPricingRecalc(frm);
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
        if (row?.item_code) {
            CGM.invalidateItemPricingRule(row.item_code);
        }
        CGM.scheduleItemPricingRecalc(frm);
    },

    form_render(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row?.item_code) {
            CGM.scheduleItemPricingRecalc(frm);
        }
    },

    rate(frm)         { CGM.scheduleItemPricingRecalc(frm); },
    qty(frm)          { CGM.scheduleItemPricingRecalc(frm); },
    amount(frm)       { CGM.scheduleItemPricingRecalc(frm); },
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

        CGM.syncCustomsTaxContext(frm, { quiet: !frm.is_dirty() });
    },

    company(frm) {
        CGM.clearTaxTypeMetaCache();
        CGM.syncCustomsTaxContext(frm);
    },
    currency(frm)        { CGM.calculateCustomsTaxes(frm); },
    conversion_rate(frm) { CGM.calculateCustomsTaxes(frm); },
    custom_weight(frm)   { CGM.calculateCustomsTaxes(frm); },
    custom_volume(frm)   { CGM.calculateCustomsTaxes(frm); },
    custom_uom(frm) {
        CGM.clearTaxTypeMetaCache();
        CGM.syncCustomsTaxContext(frm);
    },

    custom_import_cost_component_add(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_import_cost_component_remove(frm) {
        frm.trigger("recalculate_import_costs");
    },
    custom_customs_taxes_add(frm) {
        CGM.scheduleCustomsTaxRecalc(frm);
    },
    custom_customs_taxes_remove(frm) {
        CGM.scheduleCustomsTaxRecalc(frm);
    },

    items_add(frm) {
        CGM.scheduleItemPricingRecalc(frm);
    },
    items_remove(frm) {
        CGM.scheduleItemPricingRecalc(frm);
    },
});

frappe.ui.form.on("Sales Order Item", {
    item_code(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row?.item_code) {
            CGM.invalidateItemPricingRule(row.item_code);
        }
        CGM.scheduleItemPricingRecalc(frm);
    },

    form_render(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row?.item_code) {
            CGM.scheduleItemPricingRecalc(frm);
        }
    },

    rate(frm)         { CGM.scheduleItemPricingRecalc(frm); },
    qty(frm)          { CGM.scheduleItemPricingRecalc(frm); },
    amount(frm)       { CGM.scheduleItemPricingRecalc(frm); },
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

    calculation_mode(frm, cdt, cdn) {
        CGM.syncCustomsTaxFixedAmountRow(frm, cdt, cdn);
        CGM.updateCustomsTaxRowUI(frm, cdt, cdn);
        CGM.calculateCustomsTaxes(frm);
    },

    rate(frm, cdt, cdn) {
        CGM.syncCustomsTaxFixedAmountRow(frm, cdt, cdn);
        CGM.calculateCustomsTaxes(frm);
    },
    fixed_amount_kes(frm, cdt, cdn) {
        CGM.syncCustomsTaxFixedAmountRow(frm, cdt, cdn);
        CGM.calculateCustomsTaxes(frm);
    },

    form_render(frm, cdt, cdn) {
        CGM.updateCustomsTaxRowUI(frm, cdt, cdn);
        frappe.after_ajax(() => CGM.calculateCustomsTaxes(frm));
    },
});