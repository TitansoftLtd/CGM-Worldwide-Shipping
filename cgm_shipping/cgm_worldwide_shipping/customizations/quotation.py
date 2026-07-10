"""
CGM Worldwide Shipping — import-cost & customs-tax calculations.

Covers Quotation and Sales Order so that grand totals stay
consistent when a Sales Order is created from a Quotation.
"""

from __future__ import annotations

import frappe
from erpnext import get_company_currency
from erpnext.selling.doctype.quotation.quotation import Quotation
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
from frappe.utils import cint, flt, round_based_on_smallest_currency_fraction

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	QUOTATION_SI_READY_STATES,
	QUOTATION_WORKFLOW_STATE_APPROVED,
)

# ── Child-table fieldnames ────────────────────────────────────────────────────
IMPORT_COST_TABLE = "custom_import_cost_component"
CUSTOMS_TAX_TABLE = "custom_customs_taxes"

IMPORT_COST_ROW_FIELDS = (
	"charge_item",
	"amount",
	"exchange_rate",
	"amount_kes",
)

CUSTOMS_TAX_ROW_FIELDS = (
	"tax_type",
	"rate",
	"fixed_amount_kes",
	"amount_kes",
)

CGM_QUOTATION_SO_SCALAR_FIELDS = (
	"custom_weight",
	"custom_volume",
	"custom_hs_code",
	"custom_shipment_type",
	"custom_cargo_type",
	"custom_cargo_size",
	"custom_port_of_loading",
	"custom_port_of_discharge",
	"custom_transit_time_",
	"custom_commodity",
	"custom_custom_value",
	"custom_base_customs_value",
	"custom_total_tax",
	"custom_quote_clause",
	"custom_shipment",
	"custom_coo",
	"custom_idfno",
	"custom_client_ref_no",
	"custom_our_ref_no",
)

# Shipment metadata copied from Quotation to Sales Invoice when billing.
# Values are mapped explicitly because Quotation and Sales Invoice field names differ.
CGM_QUOTATION_SI_FIELD_MAP = {
	"custom_shipment": "project",
	"custom_coo": "custom_country_of_origin",
	"custom_our_ref_no": "custom_cgm_reference_no",
	"custom_idfno": "custom_idfno",
	"custom_client_ref_no": "custom_client_reference_no",
}

CGM_QUOTATION_SI_EXTRA_FIELDS = (
	"custom_shipment",
)

# ── KEBS constants ────────────────────────────────────────────────────────────
KEBS_ITEM_CODE   = "Kebs Inspection Fee"
KEBS_MIN_FOREIGN = 300.0   # minimum fee in transaction / foreign currency
KEBS_PERCENT     = 0.006   # 0.6 %

# ── Tax-type classification sets ──────────────────────────────────────────────
# Add new tax-type *names* here; no other code changes are required.
STACKING_TAX_TYPES = frozenset({"VAT"})          # stacks on the running cumulative base
EXCISE_TAX_TYPES   = frozenset({"Excise Duty"})  # stacks on customs_value + import_duty only
WEIGHT_TAX_TYPES   = frozenset({"MSS Levy"})     # rate is KES-per-ton, not a percentage
# Everything else: flat % applied directly to customs_value_kes.


# =============================================================================
# SHARED MIXIN
# =============================================================================

class _CGMCustomsTaxMixin:
    """
    Reusable customs-tax logic injected into both CGMQuotation and CGMSalesOrder.

    Concrete classes must be ERPNext selling controllers so that attributes like
    self.company, self.currency, self.conversion_rate, self.base_total and
    self.total are present.
    """

    # ── Master entry point ────────────────────────────────────────────────────

    def _calculate_import_customs_taxes(self) -> None:
        """Recalculate import-cost components, KEBS, customs taxes, and grand totals."""
        if not self.meta.has_field(IMPORT_COST_TABLE):
            self._set_custom_total_tax(0.0)
            return

        company_currency = get_company_currency(self.company)

        # Step 1 — Import Cost Component rows → customs_value
        customs_value_foreign, customs_value_kes = self._sum_import_costs(company_currency)

        self.custom_custom_value       = customs_value_foreign
        self.custom_base_customs_value = customs_value_kes

        # Step 2 — KEBS auto-calculation (item-level charge)
        self._recalculate_kebs_item(customs_value_foreign)

        # Step 3 — Customs Tax rows
        if not self.meta.has_field(CUSTOMS_TAX_TABLE):
            self._set_custom_total_tax(0.0)
            return

        total_taxes_kes = self._sum_customs_taxes(customs_value_kes)
        self._set_custom_total_tax(total_taxes_kes)

    # ── Import Cost accumulation ──────────────────────────────────────────────

    def _sum_import_costs(self, company_currency: str) -> tuple[float, float]:
        """Return (customs_value_foreign, customs_value_kes)."""
        foreign_total = 0.0
        kes_total     = 0.0

        for row in self.get(IMPORT_COST_TABLE) or []:
            self._normalize_import_cost_row(row, company_currency)
            row.amount_kes  = flt(row.amount) * flt(row.exchange_rate or 1)
            foreign_total  += flt(row.amount)
            kes_total      += row.amount_kes

        return (
            self._money(foreign_total, "custom_custom_value"),
            self._money(kes_total,     "custom_base_customs_value"),
        )

    # ── Customs Tax accumulation ──────────────────────────────────────────────

    def _sum_customs_taxes(self, customs_value_kes: float) -> float:
        """Walk customs-tax rows in idx order and return total KES tax."""
        weight_tons     = flt(self.get("custom_weight") or 0)
        running_base    = customs_value_kes   # grows as duties stack
        import_duty_kes = 0.0                 # used as base for Excise
        total_kes       = 0.0
        seen: set[str]  = set()

        for row in sorted(self.get(CUSTOMS_TAX_TABLE) or [], key=lambda r: r.idx):
            tax_type = row.tax_type
            if not tax_type:
                continue

            if tax_type in seen:
                frappe.throw(
                    frappe._("Duplicate customs tax type '{0}' is not allowed.").format(tax_type)
                )
            seen.add(tax_type)

            amount_kes, duty_delta = self._calculate_one_tax(
                row, tax_type, customs_value_kes, running_base, import_duty_kes, weight_tons
            )
            amount_kes = self._money(amount_kes, "amount_kes", row)

            row.amount_kes     = amount_kes
            row.tax_amount_kes = amount_kes   # keep legacy field in sync

            # Weight-based taxes don't alter the running base
            if tax_type not in WEIGHT_TAX_TYPES:
                running_base    += amount_kes
                import_duty_kes += duty_delta

            total_kes += amount_kes

        return total_kes

    # ── Single-row tax dispatch ───────────────────────────────────────────────

    def _calculate_one_tax(
        self,
        row,
        tax_type: str,
        customs_value_kes: float,
        running_base: float,
        import_duty_kes: float,
        weight_tons: float,
    ) -> tuple[float, float]:
        """
        Return (amount_kes, import_duty_contribution).

        import_duty_contribution is non-zero only for flat non-excise duties so
        that Excise can correctly stack on customs_value + import_duty.
        """
        # Fixed-amount override takes precedence
        calc_type = frappe.db.get_value("Customs Tax Type", tax_type, "calculation_type") or ""
        rate = flt(row.rate)

        if tax_type in WEIGHT_TAX_TYPES or calc_type == "Per Weight":
            return weight_tons * rate, 0.0

        if calc_type == "Fixed Amount" or flt(row.fixed_amount_kes) > 0:
            return flt(row.fixed_amount_kes), 0.0

        if tax_type in EXCISE_TAX_TYPES:
            return (customs_value_kes + import_duty_kes) * (rate / 100), 0.0

        if tax_type in STACKING_TAX_TYPES:
            return running_base * (rate / 100), 0.0

        # Default: flat % on raw customs_value_kes; contributes to import-duty pool
        amount_kes = customs_value_kes * (rate / 100)
        return amount_kes, amount_kes

    # ── KEBS auto-calculation ─────────────────────────────────────────────────

    def _recalculate_kebs_item(self, customs_value_foreign: float) -> None:
        """
        KEBS Inspection Fee = MAX(0.6 % of customs_value_foreign, 300 in transaction currency).
        Updates the matching Quotation / Sales Order item row in place.
        """
        kebs_rate = max(flt(customs_value_foreign) * KEBS_PERCENT, KEBS_MIN_FOREIGN)

        for item in self.get("items") or []:
            if item.item_code != KEBS_ITEM_CODE:
                continue
            item.rate = item.net_rate = flt(kebs_rate, item.precision("rate"))
            item.amount = item.net_amount = item.rate * flt(item.qty)
            item.base_rate = item.base_net_rate = self._money(
                item.rate * flt(self.conversion_rate), "base_rate", item
            )
            item.base_amount = item.base_net_amount = self._money(
                item.amount * flt(self.conversion_rate), "base_amount", item
            )

    # ── Grand-total propagation ───────────────────────────────────────────────

    def _set_custom_total_tax(self, amount_kes: float) -> None:
        if self.meta.has_field("custom_total_tax"):
            self.custom_total_tax = self._money(amount_kes, "custom_total_tax")
        self._update_grand_totals()

    def _update_grand_totals(self) -> None:
        """Grand totals = line totals + customs tax (outside the standard tax table)."""
        customs_kes = flt(getattr(self, "custom_total_tax", 0))
        customs_doc = self._to_doc_currency(customs_kes)

        if self.meta.has_field("base_grand_total"):
            self.base_grand_total = self._money(
                flt(self.base_total) + customs_kes, "base_grand_total"
            )
        if self.meta.has_field("grand_total"):
            self.grand_total = self._money(
                flt(self.total) + customs_doc, "grand_total"
            )

        self._set_rounded_totals()
        self.set_total_in_words()

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

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _to_doc_currency(self, amount_kes: float) -> float:
        if self.currency == get_company_currency(self.company):
            return flt(amount_kes)
        rate = flt(self.conversion_rate)
        return flt(amount_kes / rate, self.precision("grand_total")) if rate else 0.0

    def _normalize_import_cost_row(self, row, company_currency: str) -> None:
        """Force exchange_rate = 1 when transacting in company currency."""
        if not self.currency or self.currency == company_currency:
            row.exchange_rate = 1.0
        elif not flt(row.exchange_rate):
            row.exchange_rate = flt(self.conversion_rate) or 1.0

    def _money(self, value, fieldname: str, row=None) -> float:
        """Round to the field's configured precision."""
        if row is not None:
            return flt(value, row.precision(fieldname))
        return flt(value, self.precision(fieldname))


# =============================================================================
# QUOTATION
# =============================================================================

class CGMQuotation(_CGMCustomsTaxMixin, Quotation):

	def validate(self):
		super().validate()
		self._calculate_import_customs_taxes()
		self.set_status()

	def on_update_after_submit(self):
		self._stamp_finance_approval()

	def _stamp_finance_approval(self) -> None:
		if self.workflow_state != QUOTATION_WORKFLOW_STATE_APPROVED:
			return
		if self.custom_freight_approved_by:
			return
		self.db_set("custom_freight_approved_by", frappe.session.user, update_modified=False)


# =============================================================================
# SALES ORDER
# =============================================================================

class CGMSalesOrder(_CGMCustomsTaxMixin, SalesOrder):
    """
    Extends the standard Sales Order so that custom customs taxes (copied from
    the source Quotation) are reflected in the grand total.
    """

    def validate(self):
        super().validate()
        # Only recalculate when custom tables are present; harmless otherwise.
        if self.meta.has_field(IMPORT_COST_TABLE) or self.meta.has_field(CUSTOMS_TAX_TABLE):
            self._calculate_import_customs_taxes()


# =============================================================================
# SHARED MAPPING HELPERS
# =============================================================================

def _copy_child_table(source_doc, target_doc, table_field: str, row_fields: tuple[str, ...]) -> None:
	if not (source_doc.meta.has_field(table_field) and target_doc.meta.has_field(table_field)):
		return

	target_doc.set(table_field, [])
	for src in source_doc.get(table_field) or []:
		target_doc.append(table_field, {field: src.get(field) for field in row_fields})


def _copy_scalar_fields(source_doc, target_doc, fields: tuple[str, ...]) -> None:
	for field in fields:
		if source_doc.meta.has_field(field) and target_doc.meta.has_field(field):
			target_doc.set(field, source_doc.get(field))


def copy_cgm_quotation_fields(source_doc, target_doc) -> None:
	"""Copy full CGM customs/import fields from Quotation to Sales Order."""
	_copy_child_table(source_doc, target_doc, IMPORT_COST_TABLE, IMPORT_COST_ROW_FIELDS)
	_copy_child_table(source_doc, target_doc, CUSTOMS_TAX_TABLE, CUSTOMS_TAX_ROW_FIELDS)
	_copy_scalar_fields(source_doc, target_doc, CGM_QUOTATION_SO_SCALAR_FIELDS)

	if target_doc.meta.has_field("project") and source_doc.get("custom_shipment"):
		target_doc.project = source_doc.custom_shipment


def copy_cgm_quotation_fields_to_sales_invoice(source_doc, target_doc) -> None:
	"""Copy shipment metadata from Quotation to Sales Invoice billing fields."""
	for source_field, target_field in CGM_QUOTATION_SI_FIELD_MAP.items():
		if not source_doc.meta.has_field(source_field):
			continue
		if not target_doc.meta.has_field(target_field):
			continue
		target_doc.set(target_field, source_doc.get(source_field))

	for source_field in CGM_QUOTATION_SI_EXTRA_FIELDS:
		if not source_doc.meta.has_field(source_field):
			continue
		if not target_doc.meta.has_field(source_field):
			continue
		target_doc.set(source_field, source_doc.get(source_field))


def _validate_quotation_for_billing(quotation) -> None:
	if not quotation.meta.has_field("workflow_state"):
		return

	if quotation.workflow_state not in QUOTATION_SI_READY_STATES:
		frappe.throw(
			frappe._(
				"Sales Invoice can only be created from an Approved or Shared with Client quotation."
			),
			title=frappe._("Not Allowed"),
		)


# =============================================================================
# QUOTATION → SALES ORDER / SALES INVOICE
# =============================================================================

def on_submit_quotation(doc, method=None):
	"""Hook placeholder kept for future Quotation on_submit actions."""
	pass


@frappe.whitelist()
def make_sales_order(source_name: str, target_doc=None):
	"""Extend ERPNext mapper to carry CGM customs/import fields to Sales Order."""
	from erpnext.selling.doctype.quotation.quotation import make_sales_order as _std_make_so

	so = _std_make_so(source_name, target_doc)
	copy_cgm_quotation_fields(frappe.get_doc("Quotation", source_name), so)
	return so


@frappe.whitelist()
def make_sales_invoice(source_name: str, target_doc=None, args=None):
	"""Extend ERPNext mapper with CGM shipment metadata for the invoice print format."""
	from erpnext.selling.doctype.quotation.quotation import _make_sales_invoice

	quotation = frappe.get_doc("Quotation", source_name)
	_validate_quotation_for_billing(quotation)

	si = _make_sales_invoice(source_name, target_doc, args=args)
	copy_cgm_quotation_fields_to_sales_invoice(quotation, si)
	return si


# =============================================================================
# WHITELISTED API ENDPOINTS
# =============================================================================

@frappe.whitelist()
def get_customs_tax_type_info(tax_type: str) -> dict:
    """
    Return calculation metadata for a Customs Tax Type.
    Called from JS when a row's tax_type is selected.
    """
    if not tax_type:
        return {}

    calculation_type = frappe.db.get_value(
        "Customs Tax Type", tax_type, "calculation_type"
    ) or ""
    default_rate = _get_default_rate_from_settings(tax_type)

    is_weight_based = tax_type in WEIGHT_TAX_TYPES or calculation_type == "Per Weight"
    is_fixed        = calculation_type == "Fixed Amount" and not is_weight_based
    is_stacking     = tax_type in STACKING_TAX_TYPES
    is_excise       = tax_type in EXCISE_TAX_TYPES

    return {
        "calculation_type" : calculation_type,
        "default_rate"     : default_rate,
        "is_weight_based"  : is_weight_based,
        "is_stacking"      : is_stacking,
        "is_excise"        : is_excise,
        "is_fixed"         : is_fixed,
        "show_rate"        : is_weight_based or not is_fixed,
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
) -> dict:
    """
    Return in_words strings for live form preview.
    Mirrors SellingController.set_total_in_words.
    """
    from frappe.utils import money_in_words

    company_currency = get_company_currency(company)
    disable          = cint(disable_rounded_total)

    amount      = abs(flt(grand_total      if disable else rounded_total))
    base_amount = abs(flt(base_grand_total if disable else base_rounded_total))

    return {
        "in_words"     : money_in_words(amount,      currency)        if amount      else "",
        "base_in_words": money_in_words(base_amount, company_currency) if base_amount else "",
    }


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _get_default_rate_from_settings(tax_type: str) -> float | None:
    """
    Fetch the default rate for a tax type from CGM Shipping Settings.
    Child table: Default Customs Tax  |  Parent: CGM Shipping Settings
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