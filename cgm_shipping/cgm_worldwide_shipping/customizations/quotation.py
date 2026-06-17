"""Quotation import-cost and customs tax calculations for CGM Worldwide Shipping."""

from __future__ import annotations

import frappe
from erpnext import get_company_currency
from erpnext.selling.doctype.quotation.quotation import Quotation
from frappe.utils import cint, flt, round_based_on_smallest_currency_fraction

IMPORT_COST_TABLE  = "custom_import_cost_component"
CUSTOMS_TAX_TABLE  = "custom_customs_taxes"

# KEBS: MAX(0.6% of customs value in transaction currency, 300 in that currency)
KEBS_ITEM_CODE = "Kebs Inspection Fee"
KEBS_MIN_FOREIGN = 300.0   # minimum in the transaction/foreign currency
KEBS_PERCENT     = 0.006   # 0.6%

# These sets drive stacking logic.  Tax-type names here must match
# the "Tax Type" DocType records exactly.  Add entries as needed;
# no other code changes are required.
STACKING_TAX_TYPES = frozenset({"VAT"})
EXCISE_TAX_TYPES   = frozenset({"Excise Duty"})   # stacks on customs + import duty only
WEIGHT_TAX_TYPES   = frozenset({"MSS Levy"})
# Everything else is treated as flat % on raw customs_value_kes.


class CGMQuotation(Quotation):
    def validate(self):
        super().validate()
        self._calculate_import_customs_taxes()

    # ─────────────────────────────────────────────────────────────
    # MASTER CALCULATION
    # ─────────────────────────────────────────────────────────────

    def _calculate_import_customs_taxes(self):
        if not self.meta.has_field(IMPORT_COST_TABLE):
            self._set_custom_total_tax(0.0)
            return

        company_currency = get_company_currency(self.company)

        # ── Step 1: Import Cost Component rows ───────────────────
        import_rows = self.get(IMPORT_COST_TABLE) or []

        customs_value_foreign = 0.0   # sum of raw row.amount (foreign / doc currency)
        customs_value_kes     = 0.0   # sum of row.amount * row.exchange_rate

        for row in import_rows:
            self._normalize_import_cost_row(row, company_currency)
            row.amount_kes = flt(row.amount) * flt(row.exchange_rate or 1)
            customs_value_foreign += flt(row.amount)
            customs_value_kes     += flt(row.amount_kes)

        customs_value_foreign = self._money(customs_value_foreign, "custom_custom_value")
        customs_value_kes     = self._money(customs_value_kes,     "custom_base_customs_value")

        # custom_custom_value holds the sum in the document (foreign) currency.
        # custom_base_customs_value holds the KES equivalent.
        self.custom_custom_value       = customs_value_foreign
        self.custom_base_customs_value = customs_value_kes

        # ── Step 2: KEBS auto-calculation ────────────────────────
        # KEBS is a local charge on Quotation Items.
        # Its rate is expressed in the transaction currency (same as row.amount).
        self._recalculate_kebs_item(customs_value_foreign)

        if not self.meta.has_field(CUSTOMS_TAX_TABLE):
            self._set_custom_total_tax(0.0)
            return

        # ── Step 3: Customs Tax rows ─────────────────────────────
        weight_tons     = flt(self.get("custom_weight") or 0)
        running_base    = customs_value_kes   # accumulates as duties stack
        import_duty_kes = 0.0                 # tracked for Excise base

        total_taxes_kes = 0.0
        seen_tax_types: set[str] = set()

        tax_rows = sorted(self.get(CUSTOMS_TAX_TABLE) or [], key=lambda r: r.idx)

        for tax_row in tax_rows:
            tax_type = tax_row.tax_type
            if not tax_type:
                continue

            if tax_type in seen_tax_types:
                frappe.throw(
                    frappe._("Duplicate customs tax type {0} is not allowed.").format(tax_type)
                )
            seen_tax_types.add(tax_type)

            amount_kes, import_duty_delta = self._calculate_tax_amount(
                tax_row         = tax_row,
                tax_type        = tax_type,
                customs_value_kes = customs_value_kes,
                running_base    = running_base,
                import_duty_kes = import_duty_kes,
                weight_tons     = weight_tons,
            )

            amount_kes = self._money(amount_kes, "amount_kes", tax_row)
            tax_row.amount_kes      = amount_kes
            tax_row.tax_amount_kes  = amount_kes   # keep legacy field in sync

            # Accumulate running base for subsequent stacking taxes
            if tax_type not in WEIGHT_TAX_TYPES:
                running_base    += amount_kes
                import_duty_kes += import_duty_delta

            total_taxes_kes += flt(amount_kes)

        self._set_custom_total_tax(total_taxes_kes)

    def _set_custom_total_tax(self, amount_kes: float) -> None:
        if self.meta.has_field("custom_total_tax"):
            self.custom_total_tax = self._money(amount_kes, "custom_total_tax")
        self._update_base_grand_total()

    def _update_base_grand_total(self) -> None:
        """Grand totals = line totals + customs tax (not in total_taxes_and_charges)."""
        customs_tax = flt(self.custom_total_tax) if self.meta.has_field("custom_total_tax") else 0.0
        customs_in_doc_currency = self._to_doc_currency(customs_tax)

        if self.meta.has_field("base_grand_total"):
            self.base_grand_total = self._money(
                flt(self.base_total) + customs_tax,
                "base_grand_total",
            )

        if self.meta.has_field("grand_total"):
            self.grand_total = self._money(
                flt(self.total) + customs_in_doc_currency,
                "grand_total",
            )

        self._set_rounded_totals()
        self.set_total_in_words()

    def _to_doc_currency(self, amount_kes: float) -> float:
        company_currency = get_company_currency(self.company)
        if self.currency == company_currency:
            return flt(amount_kes)
        rate = flt(self.conversion_rate)
        if not rate:
            return 0.0
        return flt(amount_kes / rate, self.precision("grand_total"))

    def _set_rounded_totals(self) -> None:
        if self.is_rounded_total_disabled():
            self.rounded_total = self.base_rounded_total = 0.0
            self.rounding_adjustment = self.base_rounding_adjustment = 0.0
            return

        self.rounded_total = round_based_on_smallest_currency_fraction(
            self.grand_total, self.currency, self.precision("rounded_total")
        )
        self.rounding_adjustment = self._money(
            self.rounded_total - self.grand_total, "rounding_adjustment"
        )

        company_currency = get_company_currency(self.company)
        self.base_rounded_total = round_based_on_smallest_currency_fraction(
            self.base_grand_total, company_currency, self.precision("base_rounded_total")
        )
        self.base_rounding_adjustment = self._money(
            self.base_rounded_total - self.base_grand_total, "base_rounding_adjustment"
        )

    # ─────────────────────────────────────────────────────────────
    # TAX CALCULATION DISPATCH
    # ─────────────────────────────────────────────────────────────

    def _calculate_tax_amount(
        self,
        tax_row,
        tax_type: str,
        customs_value_kes: float,
        running_base: float,
        import_duty_kes: float,
        weight_tons: float,
    ) -> tuple[float, float]:
        """
        Returns (amount_kes, import_duty_contribution).

        import_duty_contribution is > 0 only for flat non-excise duties
        so Excise can stack correctly on customs_value + import_duty.
        """

        # Check DocType for Fixed Amount override
        calc_type = frappe.db.get_value(
            "Customs Tax Type", tax_type, "calculation_type"
        ) or ""

        is_fixed = (calc_type == "Fixed Amount") or (flt(tax_row.fixed_amount_kes) > 0)

        if is_fixed:
            return flt(tax_row.fixed_amount_kes), 0.0

        if tax_type in WEIGHT_TAX_TYPES:
            # Weight-based: rate field = KES per ton
            return weight_tons * flt(tax_row.rate), 0.0

        if tax_type in EXCISE_TAX_TYPES:
            # Excise stacks on (customs_value + import_duty) only
            excise_base = customs_value_kes + import_duty_kes
            return excise_base * (flt(tax_row.rate) / 100), 0.0

        if tax_type in STACKING_TAX_TYPES:
            # VAT (and any future stacking type) — on cumulative running base
            return running_base * (flt(tax_row.rate) / 100), 0.0

        # Default: flat % on raw customs_value_kes
        # Track contribution for Excise base (import duty families)
        amount_kes = customs_value_kes * (flt(tax_row.rate) / 100)
        return amount_kes, amount_kes   # contributes to import_duty pool

    # ─────────────────────────────────────────────────────────────
    # KEBS AUTO-CALCULATION
    # ─────────────────────────────────────────────────────────────

    def _recalculate_kebs_item(self, customs_value_foreign: float) -> None:
        """
        KEBS Inspection Fee = MAX(0.6% of customs_value_foreign, KEBS_MIN_FOREIGN).

        Rate is in the document's transaction currency (same as row.amount).
        Uses bank rate (self.conversion_rate) for base_* fields.
        """
        kebs_foreign = max(
            flt(customs_value_foreign) * KEBS_PERCENT,
            KEBS_MIN_FOREIGN,
        )

        for item in self.get("items") or []:
            if item.item_code == KEBS_ITEM_CODE:
                item.rate       = flt(kebs_foreign, item.precision("rate"))
                item.amount     = item.rate * flt(item.qty)
                item.net_rate   = item.rate
                item.net_amount = item.amount
                item.base_rate  = self._money(
                    item.rate * flt(self.conversion_rate), "base_rate", item)
                item.base_amount = self._money(
                    item.amount * flt(self.conversion_rate), "base_amount", item)
                item.base_net_rate   = item.base_rate
                item.base_net_amount = item.base_amount

    # ─────────────────────────────────────────────────────────────
    # EXCHANGE RATE HELPERS
    # ─────────────────────────────────────────────────────────────

    def _normalize_import_cost_row(self, row, company_currency: str) -> None:
        """If the document currency matches company currency, exchange_rate must be 1."""
        if self.currency == company_currency or not self.currency:
            row.exchange_rate = 1.0
        elif not flt(row.exchange_rate):
            # Fall back to bank rate if not set
            row.exchange_rate = flt(self.conversion_rate) or 1.0

    # ─────────────────────────────────────────────────────────────
    # PRECISION HELPER
    # ─────────────────────────────────────────────────────────────

    def _money(self, value, fieldname: str, row=None) -> float:
        if row is not None:
            return flt(value, row.precision(fieldname))
        return flt(value, self.precision(fieldname))


# ─────────────────────────────────────────────────────────────────
# WHITELISTED API
# ─────────────────────────────────────────────────────────────────

def _get_default_rate_from_settings(tax_type: str) -> float | None:
    """
    Look up the default rate for a tax type from CGM Shipping Settings.

    Child DocType : Default Customs Tax
    Parent field  : custom_default_customs_taxes
    Parent        : CGM Shipping Settings  (singleton)
    """
    try:
        result = frappe.db.get_value(
            "Default Customs Tax",
            {
                "parent"     : "CGM Shipping Settings",
                "parentfield": "custom_default_customs_taxes",
                "tax_type"   : tax_type,
            },
            "default_rate",
        )
        return flt(result) if result is not None else None
    except Exception:
        return None


@frappe.whitelist()
def get_customs_tax_type_info(tax_type: str) -> dict:
    """
    Return calculation metadata for a customs tax type.
    Called from JS when a tax_type is selected in the child table.

    - calculation_type comes from the Customs Tax Type master record.
    - default_rate comes from CGM Shipping Settings → Default Customs Taxes child table.
    """
    if not tax_type:
        return {}

    # Fetch calculation_type from Customs Tax Type master
    calculation_type = frappe.db.get_value(
        "Customs Tax Type", tax_type, "calculation_type"
    ) or ""

    # Default rate from CGM Shipping Settings child table
    default_rate = _get_default_rate_from_settings(tax_type)

    # Derive flags from calculation_type (set on the master) + known type sets
    is_fixed        = calculation_type == "Fixed Amount"
    is_weight_based = tax_type in WEIGHT_TAX_TYPES
    is_stacking     = tax_type in STACKING_TAX_TYPES
    is_excise       = tax_type in EXCISE_TAX_TYPES

    return {
        "calculation_type" : calculation_type,
        "default_rate"     : default_rate,
        "is_weight_based"  : is_weight_based,
        "is_stacking"      : is_stacking,
        "is_excise"        : is_excise,
        "is_fixed"         : is_fixed,
        "show_rate"        : not is_fixed,
        "show_fixed_amount": is_fixed,
        "rate_label"       : "Rate per Ton (KES)" if is_weight_based else "Rate (%)",
    }


@frappe.whitelist()
def get_total_in_words(
    grand_total,
    rounded_total,
    base_grand_total,
    base_rounded_total,
    currency,
    company,
    disable_rounded_total=0,
):
    """Return in_words strings for live form preview (mirrors SellingController.set_total_in_words)."""
    from frappe.utils import money_in_words

    company_currency = get_company_currency(company)
    disable = cint(disable_rounded_total)

    amount = abs(flt(grand_total if disable else rounded_total))
    base_amount = abs(flt(base_grand_total if disable else base_rounded_total))

    return {
        "in_words": money_in_words(amount, currency) if amount else "",
        "base_in_words": money_in_words(base_amount, company_currency) if base_amount else "",
    }