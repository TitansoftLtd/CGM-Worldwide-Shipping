// =============================================================================
// CGM QUOTATION & SALES ORDER — CLIENT SCRIPT
// =============================================================================
//
// Customs tax behaviour is driven by Customs Tax Type master config (fetched via
// get_customs_tax_type_info). Client preview math mirrors customs_tax_calculation.py.

const CALC_MODE_PERCENTAGE = "Percentage";
const CALC_MODE_PER_UNIT = "Per Unit";
const CALC_MODE_FIXED_AMOUNT = "Fixed Amount";
const RATE_COLUMN_LABEL = __("Rate");
const PERCENTAGE_BASE_CUSTOMS_VALUE = "Customs Value";
const PERCENTAGE_BASE_RUNNING_TAX_BASE = "Running Tax Base";

const CGM = (() => {

    // Server-fetched metadata cache  { [tax_type]: info }
    const TAX_TYPE_META = {};
    const UOM_CATEGORY_CACHE = {};

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

    function applyUomQuantityVisibility(frm, info) {
        const show_weight = !!info?.show_weight;
        const show_volume = !!info?.show_volume;
        if (frm.fields_dict.custom_weight) {
            frm.set_df_property("custom_weight", "hidden", show_weight ? 0 : 1);
        }
        if (frm.fields_dict.custom_volume) {
            frm.set_df_property("custom_volume", "hidden", show_volume ? 0 : 1);
        }
        frm._cgm_is_volume_uom = !!info?.is_volume;
    }

    function syncUomQuantityFields(frm) {
        const uom = (frm.doc.custom_uom || "").trim();
        if (!uom) {
            applyUomQuantityVisibility(frm, {
                show_weight: false,
                show_volume: false,
                is_volume: false,
            });
            return Promise.resolve(false);
        }

        if (Object.prototype.hasOwnProperty.call(UOM_CATEGORY_CACHE, uom)) {
            applyUomQuantityVisibility(frm, UOM_CATEGORY_CACHE[uom]);
            return Promise.resolve(!!UOM_CATEGORY_CACHE[uom].is_volume);
        }

        return frappe.call({
            method: "cgm_shipping.cgm_worldwide_shipping.customizations.quotation.get_uom_quantity_fields",
            args: { uom },
        }).then((r) => {
            const info = r.message || {
                show_weight: false,
                show_volume: false,
                is_volume: false,
            };
            UOM_CATEGORY_CACHE[uom] = info;
            applyUomQuantityVisibility(frm, info);
            return !!info.is_volume;
        });
    }

    function shipmentQuantity(frm) {
        if (frm._cgm_is_volume_uom) {
            return flt(frm.doc.custom_volume);
        }
        return flt(frm.doc.custom_weight);
    }

    function taxTypeMetaArgs(frm, tax_type) {
        return {
            tax_type,
            quotation_uom: frm.doc.custom_uom || "",
            company: frm.doc.company || "",
            currency: frm.doc.currency || "",
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
            syncUomQuantityFields(frm),
            prefetchTaxTypeMeta(frm),
        ]).then(() => {
            ensureCalculationModesPopulated(frm);
            refreshCustomsTaxGridUI(frm);
            calculateCustomsTaxes(frm, opts);
        });
    }

    function ensureCalculationModesPopulated(frm) {
        for (const row of frm.doc.custom_customs_taxes || []) {
            if (!row.tax_type) continue;
            const meta = TAX_TYPE_META[row.tax_type] || {};
            if (!cstr(row.calculation_mode).trim() && meta.default_calculation_mode) {
                frappe.model.set_value(
                    row.doctype,
                    row.name,
                    "calculation_mode",
                    meta.default_calculation_mode,
                    null,
                    true
                );
            }
        }
    }

    function resolveCalculationMode(row, meta = {}) {
        const mode = (row.calculation_mode || "").trim();
        if (mode) {
            return mode;
        }
        return meta.default_calculation_mode || CALC_MODE_PERCENTAGE;
    }

    function rateLabelForMode(mode, frm, meta = {}) {
        if (meta.rate_labels && meta.rate_labels[mode]) {
            return meta.rate_labels[mode];
        }
        const currency = frm.doc.currency || meta.company_currency || companyCurrency(frm);
        if (mode === CALC_MODE_PER_UNIT) {
            const uom = (frm.doc.custom_uom || __("Unit")).trim();
            return __("Rate per {0} ({1})", [uom, currency]);
        }
        if (mode === CALC_MODE_FIXED_AMOUNT) {
            return __("Fixed Amount ({0})", [currency]);
        }
        return __("Rate (%)");
    }

    function formatRateAmountDisplay(frm, doc, value) {
        const meta = TAX_TYPE_META[doc?.tax_type] || {};
        const mode = resolveCalculationMode(doc || {}, meta);
        if (value == null || value === "") {
            return "";
        }

        const currency = frm.doc.currency || meta.company_currency || companyCurrency(frm);
        const rate = flt(value);

        if (mode === CALC_MODE_PERCENTAGE) {
            return `${rate}%`;
        }
        if (mode === CALC_MODE_FIXED_AMOUNT) {
            const fixed = flt(doc.rate) || flt(doc.fixed_amount_kes);
            return currency ? `${currency} ${format_number(fixed)}` : format_number(fixed);
        }
        if (mode === CALC_MODE_PER_UNIT) {
            const uom = (frm.doc.custom_uom || __("Unit")).trim();
            return currency
                ? `${currency} ${format_number(rate)} / ${uom}`
                : `${format_number(rate)} / ${uom}`;
        }
        return value;
    }

    function formatTaxBaseDisplay(frm, doc, value) {
        if (value == null || value === "") {
            return "";
        }
        const meta = TAX_TYPE_META[doc?.tax_type] || {};
        const mode = resolveCalculationMode(doc || {}, meta);
        if (mode === CALC_MODE_FIXED_AMOUNT) {
            return "";
        }
        if (mode === CALC_MODE_PER_UNIT) {
            const uom = (frm.doc.custom_uom || __("Unit")).trim();
            return `${format_number(flt(value))} ${uom}`;
        }
        // Tax bases are calculated in company currency (same as Amount).
        const currency = meta.company_currency || companyCurrency(frm);
        return currency ? format_currency(flt(value), currency) : format_number(flt(value));
    }

    function shouldIncludeInSubsequentTaxBase(meta) {
        return !(
            meta.include_in_subsequent_tax_base === 0 ||
            meta.include_in_subsequent_tax_base === false
        );
    }

    function resolvePercentageTaxBase(meta, ctx) {
        const base = meta.percentage_base || PERCENTAGE_BASE_CUSTOMS_VALUE;
        if (
            base === PERCENTAGE_BASE_RUNNING_TAX_BASE ||
            base === "Cumulative Base" ||
            base === "Customs Value + Duty Pool"
        ) {
            return ctx.running_tax_base;
        }
        return ctx.customs_value;
    }

    function setFixedAmountValue(row, amount) {
        amount = flt(amount);
        row.rate = amount;
        row.fixed_amount_kes = amount;
        return amount;
    }

    function getFixedAmountValue(row) {
        // Grid "Rate" edits `rate`; keep that as the primary input.
        return flt(row.rate) || flt(row.fixed_amount_kes);
    }

    function syncCustomsTaxFixedAmountRow(frm, cdt, cdn, sourceField = "rate") {
        const row = locals[cdt]?.[cdn];
        if (!row?.tax_type) return;

        const meta = TAX_TYPE_META[row.tax_type] || {};
        const mode = resolveCalculationMode(row, meta);
        if (mode !== CALC_MODE_FIXED_AMOUNT) return;

        const amount =
            sourceField === "fixed_amount_kes"
                ? flt(row.fixed_amount_kes)
                : flt(row.rate);
        setFixedAmountValue(row, amount);
    }

    function calculateRowTaxAmount(frm, row, meta, ctx) {
        if (!row.tax_type) {
            return { amount: 0, tax_base: 0 };
        }

        const mode = resolveCalculationMode(row, meta);
        const rate = flt(row.rate);

        if (mode === CALC_MODE_FIXED_AMOUNT) {
            return { amount: getFixedAmountValue(row), tax_base: 0 };
        }

        if (mode === CALC_MODE_PER_UNIT) {
            const tax_base = shipmentQuantity(frm);
            return { amount: tax_base * rate, tax_base };
        }

        const tax_base = resolvePercentageTaxBase(meta, ctx);
        return { amount: tax_base * (rate / 100), tax_base };
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
        let running_tax_base = customs_value_kes;
        let total_taxes_kes = 0;

        const rows = [...(frm.doc.custom_customs_taxes || [])].sort((a, b) => a.idx - b.idx);

        for (const row of rows) {
            if (!row.tax_type) continue;

            const meta = TAX_TYPE_META[row.tax_type] || {};
            const ctx = { customs_value: customs_value_kes, running_tax_base };
            const { amount, tax_base } = calculateRowTaxAmount(frm, row, meta, ctx);

            row.tax_base = tax_base;
            row.amount_kes = amount;
            row.tax_amount_kes = amount;
            total_taxes_kes += amount;

            if (shouldIncludeInSubsequentTaxBase(meta)) {
                running_tax_base += amount;
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

            if (rule.fx_to_quotation != null && rule.fx_to_quotation !== "") {
                return flt(fixed_rate * flt(rule.fx_to_quotation));
            }
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

    function calculateItemPricingForItem(custom_value, rules, frm, selected_rule_name) {
        if (!rules?.length) return null;

        let candidates = rules;
        const selected = (selected_rule_name || "").trim();
        if (selected) {
            const matched = rules.filter((rule) => rule.name === selected);
            if (matched.length) {
                candidates = matched;
            }
        }

        let winning_rule = null;
        let winning_amount = null;

        for (const rule of candidates) {
            const amount = calculateRuleAmount(custom_value, rule, frm);
            if (winning_amount === null || amount > winning_amount) {
                winning_amount = amount;
                winning_rule = rule;
            }
        }

        if (!winning_rule) return null;

        winning_amount = flt(winning_amount);
        return {
            audit_row: {
                rule_type: ruleTypeLabel(winning_rule.calculation_type),
                percentage_rate: flt(winning_rule.percentage_rate),
                fixed_rate: flt(winning_rule.fixed_rate),
                rule_currency: winning_rule.currency,
                exchange_rate_used:
                    winning_rule.fx_to_quotation != null && winning_rule.fx_to_quotation !== ""
                        ? flt(winning_rule.fx_to_quotation)
                        : bankRate(frm),
                calculated_amount: winning_amount,
                final_applied_rate: winning_amount,
            },
            item_rate: winning_amount,
            pricing_rule: winning_rule.name || "",
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

            const result = calculateItemPricingForItem(
                custom_value,
                item_rules,
                frm,
                item.custom_selected_item_pricing_rule
            );
            if (!result) continue;

            pricing_rows.push({ item: item.item_code, ...result.audit_row });
            item_updates.push({
                name: item.name,
                item_code: item.item_code,
                rate: flt(result.audit_row.final_applied_rate),
            });
        }

        applyItemPricingResult(frm, { pricing_rows, item_updates }, opts);
        refreshItemRateEditability(frm);
    }

    function pricingRuleOptionLabel(rule, amount, currency) {
        const type = ruleTypeLabel(rule.calculation_type || CALCULATION_PERCENTAGE);
        let detail = "";
        if ((rule.calculation_type || CALCULATION_PERCENTAGE) === CALCULATION_FIXED) {
            detail = `${flt(rule.fixed_rate)} ${rule.currency || ""}`.trim();
        } else {
            detail = `${flt(rule.percentage_rate)}%`;
        }
        return `${type}: ${detail} → ${format_currency(flt(amount), currency)}`;
    }

    function quotationItemHasSelectedRuleField(frm) {
        const df = frappe.meta.get_docfield("Quotation Item", "custom_selected_item_pricing_rule");
        return Boolean(df);
    }

    function openItemPricingRulePicker(frm, cdt, cdn, rules) {
        const row = locals[cdt]?.[cdn];
        if (!row?.item_code || !rules?.length) {
            return Promise.resolve();
        }

        const custom_value = flt(frm.doc.custom_custom_value);
        const currency = frm.doc.currency;
        const options = rules.map((rule) => {
            const amount = calculateRuleAmount(custom_value, rule, frm);
            return {
                value: rule.name,
                label: pricingRuleOptionLabel(rule, amount, currency),
                amount,
            };
        });

        // Prefer currently selected, else the highest amount.
        let default_value = row.custom_selected_item_pricing_rule;
        if (!default_value || !options.some((opt) => opt.value === default_value)) {
            default_value = options.reduce((best, opt) =>
                !best || opt.amount > best.amount ? opt : best
            ).value;
        }

        return new Promise((resolve) => {
            const dialog = new frappe.ui.Dialog({
                title: __("Select Item Pricing Rule"),
                fields: [
                    {
                        fieldname: "help",
                        fieldtype: "HTML",
                        options: `<div class="text-muted" style="margin-bottom: var(--margin-sm);">
							${__("Item {0} has multiple pricing rules. Choose which rule to use for the rate.", [
								frappe.utils.escape_html(row.item_code),
							])}
						</div>`,
                    },
                    {
                        fieldname: "pricing_rule",
                        fieldtype: "Select",
                        label: __("Pricing Rule"),
                        reqd: 1,
                        options: options.map((opt) => opt.value).join("\n"),
                        default: default_value,
                    },
                ],
                primary_action_label: __("Apply Rule"),
                primary_action(values) {
                    const selected = values.pricing_rule;
                    dialog.hide();
                    frappe.model.set_value(cdt, cdn, "custom_selected_item_pricing_rule", selected).then(() => {
                        calculateItemPricing(frm);
                        resolve(selected);
                    });
                },
                secondary_action_label: __("Use highest amount"),
                secondary_action() {
                    dialog.hide();
                    frappe.model.set_value(cdt, cdn, "custom_selected_item_pricing_rule", "").then(() => {
                        calculateItemPricing(frm);
                        resolve("");
                    });
                },
            });

            const $select = dialog.fields_dict.pricing_rule.$wrapper.find("select");
            $select.empty();
            options.forEach((opt) => {
                $select.append(
                    `<option value="${frappe.utils.escape_html(opt.value)}">${frappe.utils.escape_html(
                        opt.label
                    )}</option>`
                );
            });
            $select.val(default_value);
            dialog.show();
        });
    }

    /**
     * After ERPNext get_item_details fills a selling/price-list rate:
     * - rule-driven items keep/get the pricing-rule rate (read-only)
     * - items without rules get an empty rate for the user to fill (editable)
     * - multiple rules → user picks which rule to apply
     */
    function syncItemRateAfterItemSelect(frm, cdt, cdn) {
        const row = locals[cdt]?.[cdn];
        if (!row?.item_code) {
            refreshItemRateEditability(frm);
            return;
        }

        ensureItemPricingRules([row.item_code], frm).then(() => {
            const rules = ITEM_PRICING_RULES[row.item_code] || [];
            if (!rules.length) {
                if (quotationItemHasSelectedRuleField(frm) && row.custom_selected_item_pricing_rule) {
                    frappe.model.set_value(cdt, cdn, "custom_selected_item_pricing_rule", "");
                }
                clearManualItemSellingPrice(frm, row);
                refreshItemRateEditability(frm);
                calculateItemPricing(frm);
                updateGrandTotals(frm);

                setTimeout(() => {
                    const current = locals[cdt]?.[cdn];
                    if (
                        current?.item_code === row.item_code &&
                        !itemHasPricingRules(current.item_code) &&
                        flt(current.price_list_rate)
                    ) {
                        clearManualItemSellingPrice(frm, current);
                        updateGrandTotals(frm);
                    }
                }, 250);
                return;
            }

            if (!quotationItemHasSelectedRuleField(frm)) {
                calculateItemPricing(frm);
                return;
            }

            if (rules.length === 1) {
                frappe.model
                    .set_value(cdt, cdn, "custom_selected_item_pricing_rule", rules[0].name || "")
                    .then(() => calculateItemPricing(frm));
                return;
            }

            const selected = (row.custom_selected_item_pricing_rule || "").trim();
            if (selected && rules.some((rule) => rule.name === selected)) {
                calculateItemPricing(frm);
                return;
            }

            openItemPricingRulePicker(frm, cdt, cdn, rules);
        });
    }

    function findQuotationItem(frm, upd) {
        const items = frm.doc.items || [];
        return (
            items.find((row) => row.name === upd.name && row.item_code === upd.item_code)
            || items.find((row) => row.name === upd.name)
            || items.find((row) => row.item_code === upd.item_code)
        );
    }

    function itemHasPricingRules(item_code) {
        if (!item_code || !(item_code in ITEM_PRICING_RULES)) {
            return false;
        }
        return (ITEM_PRICING_RULES[item_code] || []).length > 0;
    }

    function refreshItemRateEditability(frm) {
        const grid = frm.fields_dict.items?.grid;
        if (!grid) return;

        // Default editable; lock only rows driven by Item pricing rules.
        grid.update_docfield_property("rate", "read_only", 0);

        for (const item of frm.doc.items || []) {
            const grid_row = grid.grid_rows_by_docname?.[item.name];
            if (!grid_row) continue;

            const locked = itemHasPricingRules(item.item_code);
            if (grid_row.toggle_editable) {
                grid_row.toggle_editable("rate", !locked);
            }
            if (grid_row.grid_form?.set_df_property) {
                grid_row.grid_form.set_df_property("rate", "read_only", locked ? 1 : 0);
            }
        }
    }

    function clearManualItemSellingPrice(frm, row) {
        if (!row) return;

        row.rate = 0;
        row.price_list_rate = 0;
        row.discount_percentage = 0;
        row.discount_amount = 0;
        row.net_rate = 0;
        row.amount = 0;
        row.net_amount = 0;
        row.base_rate = 0;
        row.base_price_list_rate = 0;
        row.base_amount = 0;
        row.base_net_rate = 0;
        row.base_net_amount = 0;
        if (row.rate_with_margin != null) row.rate_with_margin = 0;
        if (row.base_rate_with_margin != null) row.base_rate_with_margin = 0;

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
        const grid_row = grid?.grid_rows_by_docname?.[row.name];
        if (!grid_row) return;
        for (const field of ["rate", "amount", "price_list_rate", "net_rate", "net_amount"]) {
            grid_row.refresh_field(field);
        }
    }

    function ensureItemPricingRules(item_codes, frm = null) {
        const codes = [...new Set((item_codes || []).filter(Boolean))];
        const missing = codes.filter((code) => !(code in ITEM_PRICING_RULES));
        if (!missing.length) {
            return Promise.resolve(ITEM_PRICING_RULES);
        }

        return frappe
            .call({
                method: "cgm_shipping.cgm_worldwide_shipping.customizations.item_pricing.get_item_pricing_rules",
                args: {
                    item_codes: missing,
                    quotation_currency: frm?.doc?.currency || "",
                    company: frm?.doc?.company || "",
                    transaction_date: frm?.doc?.transaction_date || frm?.doc?.posting_date || "",
                },
            })
            .then((r) => {
                Object.assign(ITEM_PRICING_RULES, r.message || {});
                for (const code of missing) {
                    if (!ITEM_PRICING_RULES[code]) ITEM_PRICING_RULES[code] = [];
                }
                return ITEM_PRICING_RULES;
            });
    }

    function clearItemPricingRulesCache() {
        for (const key of Object.keys(ITEM_PRICING_RULES)) {
            delete ITEM_PRICING_RULES[key];
        }
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

    /**
     * Keep custom_item_pricing in sync with Quotation items.
     * Drops audit rows whose item is no longer on the items table.
     */
    function pruneItemPricingForRemovedItems(frm) {
        if (!frm.fields_dict.custom_item_pricing) return;

        const remaining = new Set(
            (frm.doc.items || []).map((row) => row.item_code).filter(Boolean)
        );
        const rows = [...(frm.doc.custom_item_pricing || [])];
        const keep = rows.filter((row) => row.item && remaining.has(row.item));

        if (keep.length === rows.length) return;

        frm.clear_table("custom_item_pricing");
        for (const row of keep) {
            frm.add_child("custom_item_pricing", {
                item: row.item,
                rule_type: row.rule_type,
                percentage_rate: row.percentage_rate,
                fixed_rate: row.fixed_rate,
                rule_currency: row.rule_currency,
                exchange_rate_used: row.exchange_rate_used,
                calculated_amount: row.calculated_amount,
                final_applied_rate: row.final_applied_rate,
            });
        }
        frm.refresh_field("custom_item_pricing");
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
                args: {
                    item_codes,
                    quotation_currency: frm.doc.currency || "",
                    company: frm.doc.company || "",
                    transaction_date: frm.doc.transaction_date || frm.doc.posting_date || "",
                },
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

        // Always ensure Calculation Mode is populated from master default when empty.
        if (!cstr(row.calculation_mode).trim() && info.default_calculation_mode) {
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
            grid_row.refresh_field("tax_base");
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
        const allowed = meta.allowed_modes || [CALC_MODE_PERCENTAGE];
        const single_mode = allowed.length <= 1;
        const mode_read_only =
            meta.calculation_mode_read_only === true || single_mode;

        // Keep the column visible for consistency; lock it when only one mode is allowed.
        grid?.update_docfield_property("calculation_mode", "hidden", 0);

        const grid_row = grid?.grid_rows_by_docname?.[cdn];
        const row_form = grid_row?.grid_form;
        if (!row_form) return;

        row_form.set_df_property("calculation_mode", "hidden", 0);
        row_form.set_df_property("calculation_mode", "read_only", mode_read_only ? 1 : 0);
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

        if (row_form.fields_dict?.calculation_mode) {
            row_form.fields_dict.calculation_mode.get_query = () => ({
                filters: { name: ["in", allowed] },
            });
        }
    }

    function setupCustomsTaxGridHeaders(frm) {
        const grid = frm.fields_dict.custom_customs_taxes?.grid;
        if (!grid) return;

        grid.update_docfield_property("rate", "label", RATE_COLUMN_LABEL);
        grid.update_docfield_property("fixed_amount_kes", "hidden", 1);
        grid.update_docfield_property("calculation_mode", "hidden", 0);
        grid.update_docfield_property("tax_base", "read_only", 1);

        const rate_df = (grid.docfields || []).find((df) => df.fieldname === "rate");
        if (rate_df) {
            rate_df.formatter = (value, _df, doc) => {
                try {
                    return formatRateAmountDisplay(frm, doc, value);
                } catch (e) {
                    console.warn("CGM customs tax rate formatter:", e);
                }
                return value == null || value === "" ? "" : value;
            };
        }

        const tax_base_df = (grid.docfields || []).find((df) => df.fieldname === "tax_base");
        if (tax_base_df) {
            tax_base_df.formatter = (value, _df, doc) => {
                try {
                    return formatTaxBaseDisplay(frm, doc, value);
                } catch (e) {
                    console.warn("CGM customs tax base formatter:", e);
                }
                return value == null || value === "" ? "" : value;
            };
        }

        if (grid.get_field) {
            const mode_field = grid.get_field("calculation_mode");
            if (mode_field) {
                mode_field.get_query = (doc, cdt, cdn) => {
                    const row = locals[cdt]?.[cdn] || doc;
                    const meta = TAX_TYPE_META[row?.tax_type] || {};
                    const allowed = meta.allowed_modes || [CALC_MODE_PERCENTAGE];
                    return { filters: { name: ["in", allowed] } };
                };
            }
        }
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
            // Editable by default; rule-driven rows are locked in refreshItemRateEditability.
            items_grid.update_docfield_property("rate", "read_only", 0);
            items_grid.refresh();
        }

        if (frappe.meta.get_docfield("Quotation Item", "custom_selected_item_pricing_rule")) {
            frm.set_query("custom_selected_item_pricing_rule", "items", (doc, cdt, cdn) => {
                const row = locals[cdt]?.[cdn];
                return {
                    filters: {
                        parent: row?.item_code || "",
                        parenttype: "Item",
                        parentfield: "custom_item_pricing_rules",
                    },
                };
            });
        }

        const item_codes = (frm.doc.items || []).map((row) => row.item_code).filter(Boolean);
        ensureItemPricingRules(item_codes, frm).then(() => refreshItemRateEditability(frm));
    }

    function removeBlankDefaultItemRows(frm) {
        // Frappe auto-adds one empty child for reqd Table fields on new docs.
        // Local Charge Description should start empty until the user adds a row.
        if (!frm.is_new()) return;
        const items = frm.doc.items || [];
        if (!items.length) return;

        const only_blank =
            items.length === 1 &&
            !cstr(items[0].item_code).trim() &&
            !flt(items[0].qty) &&
            !flt(items[0].rate) &&
            !flt(items[0].amount);

        if (!only_blank) return;

        frm.clear_table("items");
        frm.refresh_field("items");
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
        clearItemPricingRulesCache,
        pruneItemPricingForRemovedItems,
        removeBlankDefaultItemRows,
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
        syncItemRateAfterItemSelect,
        refreshItemRateEditability,
        clearTaxTypeMetaCache,
        syncUomQuantityFields,
        enforceExchangeRate,
        toggleImportCostExchangeRate,
        seedImportCostExchangeRate,
        resolveCalculationMode,
        formatRateAmountDisplay,
        getTaxTypeMeta(tax_type) {
            return TAX_TYPE_META[tax_type] || {};
        },
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
        CGM.removeBlankDefaultItemRows(frm);
        CGM.setupImportCostGridUI(frm);
        CGM.setupCustomsTaxGridUI(frm);
        CGM.setupItemPricingGridUI(frm);
        CGM.syncUomQuantityFields(frm);
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
        CGM.clearItemPricingRulesCache();
        CGM.syncCustomsTaxContext(frm);
    },
    currency(frm) {
        CGM.clearItemPricingRulesCache();
        CGM.calculateCustomsTaxes(frm);
    },
    conversion_rate(frm) { CGM.calculateCustomsTaxes(frm); },
    custom_weight(frm)   { CGM.calculateCustomsTaxes(frm); },
    custom_volume(frm)   { CGM.calculateCustomsTaxes(frm); },
    custom_uom(frm) {
        CGM.clearTaxTypeMetaCache();
        CGM.syncUomQuantityFields(frm).then(() => CGM.syncCustomsTaxContext(frm));
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
        CGM.pruneItemPricingForRemovedItems(frm);
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
        if (!row?.item_code) {
            // Item cleared from the row — drop orphaned pricing audit rows.
            CGM.pruneItemPricingForRemovedItems(frm);
            CGM.scheduleItemPricingRecalc(frm);
            return;
        }
        CGM.invalidateItemPricingRule(row.item_code);
        // Wait for ERPNext get_item_details / price-list apply, then either
        // apply pricing-rule rates or clear selling price for manual entry.
        frappe.after_ajax(() => {
            setTimeout(() => CGM.syncItemRateAfterItemSelect(frm, cdt, cdn), 80);
        });
    },

    custom_selected_item_pricing_rule(frm, cdt, cdn) {
        CGM.scheduleItemPricingRecalc(frm);
    },

    form_render(frm) {
        CGM.refreshItemRateEditability(frm);
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
        const row = locals[cdt][cdn];
        const meta = CGM.getTaxTypeMeta(row?.tax_type);
        const mode = CGM.resolveCalculationMode(row, meta);
        // When switching to Fixed Amount, seed fixed_amount from current rate input.
        if (mode === CALC_MODE_FIXED_AMOUNT) {
            CGM.syncCustomsTaxFixedAmountRow(frm, cdt, cdn, "rate");
        }
        CGM.updateCustomsTaxRowUI(frm, cdt, cdn);
        CGM.calculateCustomsTaxes(frm);
    },

    rate(frm, cdt, cdn) {
        CGM.syncCustomsTaxFixedAmountRow(frm, cdt, cdn, "rate");
        CGM.calculateCustomsTaxes(frm);
    },
    fixed_amount_kes(frm, cdt, cdn) {
        CGM.syncCustomsTaxFixedAmountRow(frm, cdt, cdn, "fixed_amount_kes");
        CGM.calculateCustomsTaxes(frm);
    },

    form_render(frm, cdt, cdn) {
        CGM.updateCustomsTaxRowUI(frm, cdt, cdn);
        frappe.after_ajax(() => CGM.calculateCustomsTaxes(frm));
    },
});