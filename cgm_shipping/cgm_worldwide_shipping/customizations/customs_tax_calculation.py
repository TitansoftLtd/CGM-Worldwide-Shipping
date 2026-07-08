"""Configuration-driven customs-tax calculation for Quotation and Sales Order.

All behavioural rules come from the **Customs Tax Type** master.
All volume vs weight decisions come from standard ERPNext **UOM.category**.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe
from erpnext import get_company_currency
from frappe import _
from frappe.utils import cint, flt

CALC_MODE_PERCENTAGE = "Percentage"
CALC_MODE_PER_UNIT = "Per Unit"
CALC_MODE_FIXED_AMOUNT = "Fixed Amount"
VALID_CALCULATION_MODES = frozenset(
	{CALC_MODE_PERCENTAGE, CALC_MODE_PER_UNIT, CALC_MODE_FIXED_AMOUNT}
)

FIELD_UOM = "custom_uom"
FIELD_WEIGHT = "custom_weight"
FIELD_VOLUME = "custom_volume"
# TODO: rename when a dedicated field-rename migration exists.
FIELD_FIXED_AMOUNT = "fixed_amount_kes"

UOM_CATEGORY_VOLUME = "Volume"


@dataclass(frozen=True)
class TaxTypeConfig:
	tax_type: str
	allowed_modes: tuple[str, ...]
	default_mode: str
	is_stacking: bool
	is_excise: bool
	affects_import_duty: bool
	feeds_running_base: bool
	per_unit_skips_running_base: bool


# ── Customs Tax Type configuration ───────────────────────────────────────────


def parse_allowed_modes(raw: str | None) -> tuple[str, ...]:
	modes = []
	for line in (raw or "").splitlines():
		mode = line.strip()
		if mode in VALID_CALCULATION_MODES and mode not in modes:
			modes.append(mode)
	return tuple(modes)


def get_tax_type_config(tax_type: str) -> TaxTypeConfig:
	"""Load calculation behaviour from Customs Tax Type. Raises if incomplete."""
	if not tax_type:
		frappe.throw(_("Customs tax type is required."))

	doc = frappe.get_cached_doc("Customs Tax Type", tax_type)
	allowed = parse_allowed_modes(doc.get("allowed_calculation_modes"))
	if not allowed:
		frappe.throw(
			_("Customs Tax Type '{0}' has no Allowed Calculation Modes configured.").format(
				tax_type
			)
		)

	default_mode = (doc.get("default_calculation_mode") or "").strip()
	if default_mode not in allowed:
		frappe.throw(
			_(
				"Customs Tax Type '{0}' has Default Calculation Mode '{1}' "
				"which is not in Allowed Calculation Modes."
			).format(tax_type, default_mode or _("(empty)"))
		)

	return TaxTypeConfig(
		tax_type=tax_type,
		allowed_modes=allowed,
		default_mode=default_mode,
		is_stacking=bool(cint(doc.get("is_stacking"))),
		is_excise=bool(cint(doc.get("is_excise"))),
		affects_import_duty=bool(cint(doc.get("affects_import_duty"))),
		feeds_running_base=bool(cint(doc.get("feeds_running_base"))),
		per_unit_skips_running_base=bool(cint(doc.get("per_unit_skips_running_base"))),
	)


def allowed_modes_for_tax(tax_type: str) -> tuple[str, ...]:
	return get_tax_type_config(tax_type).allowed_modes


def default_mode_for_tax(tax_type: str) -> str:
	return get_tax_type_config(tax_type).default_mode


def resolve_calculation_mode(row, tax_type: str) -> str:
	"""Return the row's mode if set, else the tax type default. Never silently remaps."""
	config = get_tax_type_config(tax_type)
	mode = (row.get("calculation_mode") or "").strip()
	if not mode:
		return config.default_mode
	return mode


def validate_calculation_mode(row, tax_type: str) -> str:
	"""Ensure the row mode is allowed; throw with a clear message if not."""
	config = get_tax_type_config(tax_type)
	mode = resolve_calculation_mode(row, tax_type)
	if mode not in config.allowed_modes:
		frappe.throw(
			_(
				"Calculation Mode '{0}' is not allowed for Customs Tax Type '{1}'. "
				"Allowed modes: {2}."
			).format(mode, tax_type, ", ".join(config.allowed_modes))
		)
	return mode


# ── Currency / UOM helpers ───────────────────────────────────────────────────


def resolve_company_currency(doc=None, company: str | None = None) -> str:
	if company:
		return get_company_currency(company)

	if doc is not None:
		doc_company = doc.get("company") if hasattr(doc, "get") else getattr(doc, "company", None)
		if doc_company:
			return get_company_currency(doc_company)

	default_company = frappe.defaults.get_global_default("company")
	if default_company:
		return get_company_currency(default_company)

	return frappe.defaults.get_global_default("currency") or ""


@frappe.request_cache
def get_uom_category(uom: str | None) -> str | None:
	uom = (uom or "").strip()
	if not uom or not frappe.db.exists("UOM", uom):
		return None
	return frappe.db.get_value("UOM", uom, "category")


def is_volume_uom(uom: str | None) -> bool:
	return get_uom_category(uom) == UOM_CATEGORY_VOLUME


def shipment_quantity(doc) -> float:
	uom = (doc.get(FIELD_UOM) or "").strip()
	if is_volume_uom(uom):
		return flt(doc.get(FIELD_VOLUME))
	return flt(doc.get(FIELD_WEIGHT))


def rate_label_for_mode(
	mode: str,
	quotation_uom: str | None = None,
	currency: str | None = None,
) -> str:
	currency = currency or resolve_company_currency()
	if mode == CALC_MODE_PER_UNIT:
		uom = (quotation_uom or _("Unit")).strip()
		return _("Rate per {0} ({1})").format(uom, currency)
	if mode == CALC_MODE_FIXED_AMOUNT:
		return _("Fixed Amount ({0})").format(currency)
	return _("Rate (%)")


# ── Row calculation (single-purpose helpers) ─────────────────────────────────


def should_feed_running_base(tax_type: str, mode: str) -> bool:
	config = get_tax_type_config(tax_type)
	if not config.feeds_running_base:
		return False
	if mode == CALC_MODE_PER_UNIT and config.per_unit_skips_running_base:
		return False
	return True


def import_duty_contribution(tax_type: str, mode: str, amount_kes: float) -> float:
	config = get_tax_type_config(tax_type)
	if config.is_excise or config.is_stacking:
		return 0.0
	if mode == CALC_MODE_PER_UNIT and config.per_unit_skips_running_base:
		return 0.0
	if mode == CALC_MODE_FIXED_AMOUNT:
		return 0.0
	if not config.affects_import_duty:
		return 0.0
	return amount_kes


def _fixed_amount(row) -> float:
	# Prefer rate (grid editable column), then dedicated fixed field.
	return flt(row.rate) or flt(row.get(FIELD_FIXED_AMOUNT))


def _percentage_amount(config: TaxTypeConfig, rate: float, *, customs_value_kes: float, running_base: float, import_duty_kes: float) -> float:
	if config.is_excise:
		return (customs_value_kes + import_duty_kes) * (rate / 100)
	if config.is_stacking:
		return running_base * (rate / 100)
	return customs_value_kes * (rate / 100)


def calculate_tax_amount(
	row,
	tax_type: str,
	*,
	customs_value_kes: float,
	running_base: float,
	import_duty_kes: float,
	shipment_qty: float,
) -> float:
	config = get_tax_type_config(tax_type)
	mode = validate_calculation_mode(row, tax_type)
	rate = flt(row.rate)

	if mode == CALC_MODE_FIXED_AMOUNT:
		return _fixed_amount(row)

	if mode == CALC_MODE_PER_UNIT:
		return shipment_qty * rate

	return _percentage_amount(
		config,
		rate,
		customs_value_kes=customs_value_kes,
		running_base=running_base,
		import_duty_kes=import_duty_kes,
	)
