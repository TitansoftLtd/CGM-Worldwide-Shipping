"""Starter Customs Tax Type + default-rate data for fresh installs only.

Not used by the calculation engine at runtime. Existing sites keep their masters
unless a migration explicitly reapplies seed behaviour for known tax names.
"""

from __future__ import annotations

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	CALC_MODE_FIXED_AMOUNT,
	CALC_MODE_PERCENTAGE,
	CALC_MODE_PER_UNIT,
	PERCENTAGE_BASE_CUSTOMS_VALUE,
	PERCENTAGE_BASE_RUNNING_TAX_BASE,
)

CUSTOMS_CALCULATION_MODES: list[dict] = [
	{
		"mode_name": CALC_MODE_PERCENTAGE,
		"description": "Apply a percentage rate to the configured percentage base.",
	},
	{
		"mode_name": CALC_MODE_PER_UNIT,
		"description": "Multiply a per-unit rate by shipment weight or volume (from UOM).",
	},
	{
		"mode_name": CALC_MODE_FIXED_AMOUNT,
		"description": "Charge a fixed amount in company currency.",
	},
]


def _modes(*modes: str) -> list[dict]:
	return [{"calculation_mode": mode} for mode in modes]


CUSTOMS_TAX_TYPES: list[dict] = [
	{
		"tax_name": "Duty",
		"allowed_calculation_modes": _modes(CALC_MODE_PERCENTAGE),
		"default_calculation_mode": CALC_MODE_PERCENTAGE,
		"percentage_base": PERCENTAGE_BASE_CUSTOMS_VALUE,
		"include_in_subsequent_tax_base": 1,
	},
	{
		"tax_name": "Excise Duty",
		"allowed_calculation_modes": _modes(CALC_MODE_PERCENTAGE, CALC_MODE_FIXED_AMOUNT),
		"default_calculation_mode": CALC_MODE_PERCENTAGE,
		"percentage_base": PERCENTAGE_BASE_RUNNING_TAX_BASE,
		"include_in_subsequent_tax_base": 1,
	},
	{
		"tax_name": "VAT",
		"allowed_calculation_modes": _modes(CALC_MODE_PERCENTAGE),
		"default_calculation_mode": CALC_MODE_PERCENTAGE,
		"percentage_base": PERCENTAGE_BASE_RUNNING_TAX_BASE,
		"include_in_subsequent_tax_base": 0,
	},
	{
		"tax_name": "IDF",
		"allowed_calculation_modes": _modes(CALC_MODE_PERCENTAGE),
		"default_calculation_mode": CALC_MODE_PERCENTAGE,
		"percentage_base": PERCENTAGE_BASE_CUSTOMS_VALUE,
		"include_in_subsequent_tax_base": 0,
	},
	{
		"tax_name": "RDL",
		"allowed_calculation_modes": _modes(CALC_MODE_PERCENTAGE),
		"default_calculation_mode": CALC_MODE_PERCENTAGE,
		"percentage_base": PERCENTAGE_BASE_CUSTOMS_VALUE,
		"include_in_subsequent_tax_base": 0,
	},
	{
		"tax_name": "MSS Levy",
		"allowed_calculation_modes": _modes(CALC_MODE_PERCENTAGE, CALC_MODE_PER_UNIT),
		"default_calculation_mode": CALC_MODE_PER_UNIT,
		"percentage_base": PERCENTAGE_BASE_CUSTOMS_VALUE,
		"include_in_subsequent_tax_base": 0,
	},
]

DEFAULT_CUSTOMS_TAX_RATES: dict[str, float] = {
	"VAT": 16,
	"IDF": 2.5,
	"RDL": 2,
}
