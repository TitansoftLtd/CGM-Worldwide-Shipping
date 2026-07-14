"""Configuration-driven customs-tax calculation for Quotation and Sales Order.

All behavioural rules come from the **Customs Tax Type** master.
All volume vs weight decisions come from standard ERPNext **UOM.category**.

The engine never branches on tax names. New Customs Tax Types work without
code changes.
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

PERCENTAGE_BASE_CUSTOMS_VALUE = "Customs Value"
PERCENTAGE_BASE_RUNNING_TAX_BASE = "Running Tax Base"
VALID_PERCENTAGE_BASES = frozenset(
	{
		PERCENTAGE_BASE_CUSTOMS_VALUE,
		PERCENTAGE_BASE_RUNNING_TAX_BASE,
	}
)

# Legacy Select values kept for migration mapping only.
_LEGACY_PERCENTAGE_BASE_CUMULATIVE = "Cumulative Base"
_LEGACY_PERCENTAGE_BASE_CUSTOMS_PLUS_DUTY = "Customs Value + Duty Pool"

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
	percentage_base: str
	include_in_subsequent_tax_base: bool


@dataclass(frozen=True)
class TaxCalculationResult:
	"""Result of calculating one customs-tax row."""

	amount: float
	tax_base: float
	mode: str


# ── Customs Tax Type configuration ───────────────────────────────────────────


def parse_allowed_modes(raw) -> tuple[str, ...]:
	"""Parse allowed modes from legacy newline text, a list, or child-table rows."""
	modes: list[str] = []

	if raw is None:
		return tuple()

	if isinstance(raw, str):
		candidates = [line.strip() for line in raw.splitlines()]
	elif isinstance(raw, (list, tuple)):
		candidates = []
		for item in raw:
			if isinstance(item, str):
				candidates.append(item.strip())
			elif isinstance(item, dict):
				candidates.append(cstr_mode(item.get("calculation_mode")))
			else:
				candidates.append(cstr_mode(getattr(item, "calculation_mode", None)))
	else:
		return tuple()

	for mode in candidates:
		if mode in VALID_CALCULATION_MODES and mode not in modes:
			modes.append(mode)
	return tuple(modes)


def cstr_mode(value) -> str:
	return (value or "").strip() if isinstance(value, str) else str(value or "").strip()


def allowed_modes_from_doc(doc) -> tuple[str, ...]:
	"""Read allowed modes from a Customs Tax Type document (child table or legacy text)."""
	rows = doc.get("allowed_calculation_modes")
	if rows and not isinstance(rows, str):
		return parse_allowed_modes(rows)
	return parse_allowed_modes(rows if isinstance(rows, str) else None)


def normalize_percentage_base(value: str | None) -> str:
	"""Map legacy percentage-base labels onto the current Select options."""
	base = cstr_mode(value) or PERCENTAGE_BASE_CUSTOMS_VALUE
	if base in (
		_LEGACY_PERCENTAGE_BASE_CUMULATIVE,
		_LEGACY_PERCENTAGE_BASE_CUSTOMS_PLUS_DUTY,
		PERCENTAGE_BASE_RUNNING_TAX_BASE,
	):
		return PERCENTAGE_BASE_RUNNING_TAX_BASE
	if base == PERCENTAGE_BASE_CUSTOMS_VALUE:
		return PERCENTAGE_BASE_CUSTOMS_VALUE
	return base


def get_tax_type_config(tax_type: str) -> TaxTypeConfig:
	"""Load calculation behaviour from Customs Tax Type. Raises if incomplete."""
	if not tax_type:
		frappe.throw(_("Customs tax type is required."))

	doc = frappe.get_cached_doc("Customs Tax Type", tax_type)
	allowed = allowed_modes_from_doc(doc)
	if not allowed:
		frappe.throw(
			_("Customs Tax Type '{0}' has no Allowed Calculation Modes configured.").format(
				tax_type
			)
		)

	default_mode = cstr_mode(doc.get("default_calculation_mode"))
	if default_mode not in allowed:
		frappe.throw(
			_(
				"Customs Tax Type '{0}' has Default Calculation Mode '{1}' "
				"which is not in Allowed Calculation Modes."
			).format(tax_type, default_mode or _("(empty)"))
		)

	percentage_base = normalize_percentage_base(doc.get("percentage_base"))
	if percentage_base not in VALID_PERCENTAGE_BASES:
		frappe.throw(
			_(
				"Customs Tax Type '{0}' has invalid Percentage Base '{1}'. "
				"Valid options: {2}."
			).format(tax_type, percentage_base, ", ".join(sorted(VALID_PERCENTAGE_BASES)))
		)

	include_flag = doc.get("include_in_subsequent_tax_base")
	if include_flag is None and doc.get("include_in_duty_pool") is not None:
		# Transient compatibility while a site is mid-migration.
		include_flag = doc.get("include_in_duty_pool")

	return TaxTypeConfig(
		tax_type=tax_type,
		allowed_modes=allowed,
		default_mode=default_mode,
		percentage_base=percentage_base,
		include_in_subsequent_tax_base=bool(cint(include_flag)),
	)


def allowed_modes_for_tax(tax_type: str) -> tuple[str, ...]:
	return get_tax_type_config(tax_type).allowed_modes


def default_mode_for_tax(tax_type: str) -> str:
	return get_tax_type_config(tax_type).default_mode


def resolve_calculation_mode(row, tax_type: str) -> str:
	"""Return the row's mode if set, else the tax type default. Never silently remaps."""
	config = get_tax_type_config(tax_type)
	mode = cstr_mode(row.get("calculation_mode"))
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


def format_rate_display(
	mode: str,
	rate: float,
	*,
	quotation_uom: str | None = None,
	currency: str | None = None,
) -> str:
	"""Human-readable rate for grids and labels, e.g. '25%', 'KES 250', 'KES 10 / Litre'."""
	currency = currency or resolve_company_currency()
	rate_str = _format_rate_number(rate)

	if mode == CALC_MODE_PERCENTAGE:
		return f"{rate_str}%"

	if mode == CALC_MODE_FIXED_AMOUNT:
		if currency:
			return f"{currency} {rate_str}"
		return rate_str

	if mode == CALC_MODE_PER_UNIT:
		uom = (quotation_uom or _("Unit")).strip()
		if currency:
			return f"{currency} {rate_str} / {uom}"
		return f"{rate_str} / {uom}"

	return rate_str


def _format_rate_number(rate: float) -> str:
	"""Compact float formatting that drops trailing zeros (25 not 25.0)."""
	rate = flt(rate)
	if rate == int(rate):
		return str(int(rate))
	return f"{rate:g}"


def rate_display_suffix(
	mode: str,
	quotation_uom: str | None = None,
	currency: str | None = None,
) -> str:
	"""Short suffix/unit for grid Rate display."""
	if mode == CALC_MODE_PERCENTAGE:
		return "%"
	if mode == CALC_MODE_PER_UNIT:
		return (quotation_uom or _("Unit")).strip()
	return currency or resolve_company_currency()


# ── Row calculation (single-purpose helpers) ─────────────────────────────────


def should_include_in_subsequent_tax_base(tax_type: str) -> bool:
	"""Whether this tax amount should grow the Running Tax Base for later taxes."""
	return get_tax_type_config(tax_type).include_in_subsequent_tax_base


def resolve_tax_base(
	config: TaxTypeConfig,
	mode: str,
	*,
	customs_value: float,
	running_tax_base: float,
	shipment_qty: float,
) -> float:
	"""Return the numeric base the engine uses for this row's calculation."""
	if mode == CALC_MODE_FIXED_AMOUNT:
		return 0.0
	if mode == CALC_MODE_PER_UNIT:
		return flt(shipment_qty)
	if config.percentage_base == PERCENTAGE_BASE_RUNNING_TAX_BASE:
		return flt(running_tax_base)
	return flt(customs_value)


def _fixed_amount(row) -> float:
	# Prefer rate (grid editable column), then dedicated fixed field.
	return flt(row.rate) or flt(row.get(FIELD_FIXED_AMOUNT))


def _percentage_amount(tax_base: float, rate: float) -> float:
	return flt(tax_base) * (flt(rate) / 100)


def calculate_tax_amount(
	row,
	tax_type: str,
	*,
	customs_value: float,
	running_tax_base: float,
	shipment_qty: float,
) -> TaxCalculationResult:
	"""Calculate one tax row from Customs Tax Type configuration.

	Does not update the Running Tax Base — the caller decides whether to include
	the result via ``should_include_in_subsequent_tax_base``.
	"""
	config = get_tax_type_config(tax_type)
	mode = validate_calculation_mode(row, tax_type)
	tax_base = resolve_tax_base(
		config,
		mode,
		customs_value=customs_value,
		running_tax_base=running_tax_base,
		shipment_qty=shipment_qty,
	)

	if mode == CALC_MODE_FIXED_AMOUNT:
		amount = _fixed_amount(row)
	elif mode == CALC_MODE_PER_UNIT:
		amount = flt(shipment_qty) * flt(row.rate)
	else:
		amount = _percentage_amount(tax_base, row.rate)

	return TaxCalculationResult(amount=flt(amount), tax_base=flt(tax_base), mode=mode)
