"""Quotation import-cost and customs tax calculations for CGM Worldwide Shipping."""

from __future__ import annotations

import frappe
from erpnext import get_company_currency
from erpnext.selling.doctype.quotation.quotation import Quotation
from erpnext.setup.utils import get_exchange_rate
from frappe.utils import flt, round_based_on_smallest_currency_fraction

IMPORT_COST_TABLE = "custom_import_cost_component"
CUSTOMS_TAX_TABLE = "custom_customs_taxes"
USD_CURRENCY = "USD"

# Tax types that stack (each calculated on base + all prior taxes)
STACKING_TAX_TYPES = frozenset({"VAT"})

# Tax types calculated on the raw customs value (no stacking)
FLAT_TAX_TYPES = frozenset({"Import Duty", "Excise Duty", "IDF", "RDL"})

# Tax types that use weight × rate_per_ton (not customs value)
WEIGHT_BASED_TAX_TYPES = frozenset({"MSS Levy"})

# KEBS: MAX(0.6% of customs value USD, 300 USD)
KEBS_ITEM_CODE = "Kebs Inspection Fee"
KEBS_MIN_USD = 300.0
KEBS_PERCENT = 0.006  # 0.6%


class CGMQuotation(Quotation):
    def validate(self):
        super().validate()
        self._calculate_import_customs_taxes()

    # ─────────────────────────────────────────────────────────────
    # MASTER CALCULATION
    # ─────────────────────────────────────────────────────────────

    def _calculate_import_customs_taxes(self):
        if not self.meta.has_field(IMPORT_COST_TABLE):
            return

        company_currency = get_company_currency(self.company)

        # ── Step 1: Import Cost Component rows ───────────────────
        # Each row has its OWN exchange_rate (company chosen for customs).
        # Local charges on the Quotation items use self.conversion_rate (bank rate).
        import_rows = self.get(IMPORT_COST_TABLE) or []
        customs_value_kes = 0.0
        customs_value_usd = 0.0

        for row in import_rows:
            self._normalize_import_cost_row(row, company_currency)
            row.amount_kes = self._to_kes(row.amount, row.currency, row.exchange_rate, company_currency)
            customs_value_kes += flt(row.amount_kes)

            # Customs value in USD: convert everything through KES then to USD
            usd_rate = self._get_usd_rate(import_rows, company_currency)
            customs_value_usd += flt(row.amount_kes / usd_rate) if usd_rate else 0.0

        customs_value_kes = self._money(customs_value_kes, "custom_base_customs_value")
        customs_value_usd = self._money(customs_value_usd, "custom_custom_value")

        self.custom_base_customs_value = customs_value_kes
        self.custom_custom_value = customs_value_usd

        # ── Step 2: KEBS auto-calculation on Quotation Items ─────
        # KEBS = MAX(0.6% of customs_value_usd, 300 USD)
        # Uses bank rate (self.conversion_rate) — local charge
        self._recalculate_kebs_item(customs_value_usd)

        if not self.meta.has_field(CUSTOMS_TAX_TABLE):
            return

        # ── Step 3: Customs Tax rows ─────────────────────────────
        # Taxes are applied in ORDER of idx. VAT stacks on top of
        # customs_value + all duties already calculated. Others are flat
        # against customs_value_kes.
        usd_rate = self._get_usd_rate(import_rows, company_currency)
        weight_tons = flt(self.get("custom_weight") or 0)

        running_base_kes = customs_value_kes  # base that grows as duties stack
        total_taxes_kes = 0.0
        total_taxes_usd = 0.0
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

            amount_kes = self._calculate_tax_amount(
                tax_row=tax_row,
                tax_type=tax_type,
                customs_value_kes=customs_value_kes,
                running_base_kes=running_base_kes,
                weight_tons=weight_tons,
            )

            amount_kes = self._money(amount_kes, "amount_kes", tax_row)
            amount_usd = self._money(
                flt(amount_kes / usd_rate) if usd_rate else 0.0,
                "amount_usd",
                tax_row,
            )

            tax_row.amount_kes = amount_kes
            tax_row.amount_usd = amount_usd

            # VAT and stacking taxes grow the running base for subsequent rows
            if tax_type in STACKING_TAX_TYPES:
                running_base_kes += amount_kes

            total_taxes_kes += flt(amount_kes)
            total_taxes_usd += flt(amount_usd)

        self.custom_total_taxes_kes = self._money(total_taxes_kes, "custom_total_taxes_kes")
        if self.meta.has_field("custom_total_taxes_usd"):
            self.custom_total_taxes_usd = self._money(total_taxes_usd, "custom_total_taxes_usd")

        self._apply_customs_to_standard_totals(total_taxes_kes)

    # ─────────────────────────────────────────────────────────────
    # TAX CALCULATION DISPATCH
    # ─────────────────────────────────────────────────────────────

    def _calculate_tax_amount(
        self,
        tax_row,
        tax_type: str,
        customs_value_kes: float,
        running_base_kes: float,
        weight_tons: float,
    ) -> float:
        """Route to correct calculation method based on tax type."""

        # Fixed amount (e.g. a flat KES fee set directly on the row)
        calculation_type = frappe.db.get_value(
            "Customs Tax Type", tax_type, "calculation_type"
        ) or ""

        if calculation_type == "Fixed Amount" or flt(tax_row.fixed_amount_kes) > 0:
            return flt(tax_row.fixed_amount_kes)

        # Weight-based (MSS Levy = weight_tons × rate_per_ton)
        if tax_type in WEIGHT_BASED_TAX_TYPES:
            # rate field = KES per ton
            return weight_tons * flt(tax_row.rate)

        # Stacking (VAT is on customs_value + all prior duties)
        if tax_type in STACKING_TAX_TYPES:
            return running_base_kes * (flt(tax_row.rate) / 100)

        # Flat percentage on raw customs value (Import Duty, IDF, RDL, Excise)
        return customs_value_kes * (flt(tax_row.rate) / 100)

    # ─────────────────────────────────────────────────────────────
    # KEBS AUTO-CALCULATION
    # ─────────────────────────────────────────────────────────────

    def _recalculate_kebs_item(self, customs_value_usd: float) -> None:
        """
        KEBS Inspection Fee = MAX(0.6% of customs_value_usd, 300 USD).
        Uses the bank rate (self.conversion_rate) — it's a local charge.
        Updates the matching Quotation Item in place.
        """
        kebs_usd = max(
            flt(customs_value_usd) * KEBS_PERCENT,
            KEBS_MIN_USD,
        )

        for item in self.get("items") or []:
            if item.item_code == KEBS_ITEM_CODE:
                item.rate = flt(kebs_usd, item.precision("rate"))
                item.amount = item.rate * flt(item.qty)
                item.net_rate = item.rate
                item.net_amount = item.amount
                item.base_rate = self._money(item.rate * flt(self.conversion_rate), "base_rate", item)
                item.base_amount = self._money(item.amount * flt(self.conversion_rate), "base_amount", item)
                item.base_net_rate = item.base_rate
                item.base_net_amount = item.base_amount

    # ─────────────────────────────────────────────────────────────
    # TOTALS INTEGRATION
    # ─────────────────────────────────────────────────────────────

    def _apply_customs_to_standard_totals(self, total_taxes_kes: float) -> None:
        """Push customs taxes into ERPNext standard total fields."""
        customs_in_doc_currency = self._to_doc_currency(total_taxes_kes)
        if not customs_in_doc_currency:
            return

        self.total_taxes_and_charges = self._money(
            flt(self.total_taxes_and_charges) + customs_in_doc_currency,
            "total_taxes_and_charges",
        )
        self.base_total_taxes_and_charges = self._money(
            flt(self.base_total_taxes_and_charges) + flt(total_taxes_kes),
            "base_total_taxes_and_charges",
        )
        self.grand_total = self._money(
            flt(self.net_total) + flt(self.total_taxes_and_charges),
            "grand_total",
        )
        self.base_grand_total = self._money(
            flt(self.grand_total) * flt(self.conversion_rate),
            "base_grand_total",
        )
        self._set_rounded_totals()
        self.set_total_in_words()

    def _to_doc_currency(self, amount_kes: float) -> float:
        """Convert KES amount to the document's transaction currency."""
        company_currency = get_company_currency(self.company)
        if self.currency == company_currency:
            return flt(amount_kes)
        rate = flt(self.conversion_rate)
        if not rate:
            return 0.0
        return flt(amount_kes / rate, self.precision("total_taxes_and_charges"))

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
        self.base_rounded_total = self._money(
            self.rounded_total * flt(self.conversion_rate), "base_rounded_total"
        )
        self.base_rounding_adjustment = self._money(
            self.base_rounded_total - self.base_grand_total, "base_rounding_adjustment"
        )

    # ─────────────────────────────────────────────────────────────
    # EXCHANGE RATE HELPERS
    # ─────────────────────────────────────────────────────────────

    def _normalize_import_cost_row(self, row, company_currency: str) -> None:
        """If the row is in company currency, exchange rate must be 1."""
        if row.currency == company_currency:
            row.exchange_rate = 1.0

    def _to_kes(
        self,
        amount: float,
        currency: str,
        exchange_rate: float,
        company_currency: str,
    ) -> float:
        """
        Convert any amount to KES using the ROW's own exchange_rate.
        This is the company-chosen rate for customs purposes — NOT the bank rate.
        """
        if currency == company_currency:
            return flt(amount)
        return flt(amount) * flt(exchange_rate)

    def _get_usd_rate(self, rows, company_currency: str) -> float:
        """
        KES per 1 USD.
        Prefer: exchange_rate from a USD import-cost row (company chosen).
        Fallback: ERPNext live exchange rate.
        """
        for row in rows:
            if row.currency == USD_CURRENCY and flt(row.exchange_rate):
                return flt(row.exchange_rate)
        return flt(
            get_exchange_rate(USD_CURRENCY, company_currency, self.transaction_date) or 0
        )

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

@frappe.whitelist()
def get_customs_tax_type_info(tax_type: str) -> dict:
    """
    Return calculation metadata for a customs tax type.
    Called from JS when a tax_type is selected in the child table.
    """
    if not tax_type:
        return {}

    doc = frappe.db.get_value(
        "Customs Tax Type",
        tax_type,
        ["calculation_type", "default_rate"],
        as_dict=True,
    ) or {}

    is_weight_based = tax_type in WEIGHT_BASED_TAX_TYPES
    is_stacking = tax_type in STACKING_TAX_TYPES
    is_fixed = doc.get("calculation_type") == "Fixed Amount"

    return {
        "calculation_type": doc.get("calculation_type"),
        "default_rate": doc.get("default_rate"),
        "is_weight_based": is_weight_based,
        "is_stacking": is_stacking,
        "is_fixed": is_fixed,
        # UI hints for JS
        "show_rate": not is_fixed,
        "show_fixed_amount": is_fixed,
        "rate_label": "Rate per Ton (KES)" if is_weight_based else "Rate (%)",
    }