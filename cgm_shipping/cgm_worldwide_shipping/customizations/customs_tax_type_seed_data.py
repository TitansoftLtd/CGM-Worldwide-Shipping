"""Starter Customs Tax Type + default-rate data for fresh installs only.

Not used by the calculation engine at runtime. Existing sites keep their masters.
"""

from __future__ import annotations

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	CALC_MODE_FIXED_AMOUNT,
	CALC_MODE_PERCENTAGE,
	CALC_MODE_PER_UNIT,
)

CUSTOMS_TAX_TYPES: list[dict] = [
	{
		"tax_name": "Duty",
		"calculation_type": "Percentage",
		"allowed_calculation_modes": CALC_MODE_PERCENTAGE,
		"default_calculation_mode": CALC_MODE_PERCENTAGE,
		"is_stacking": 0,
		"is_excise": 0,
		"affects_import_duty": 1,
		"feeds_running_base": 1,
		"per_unit_skips_running_base": 0,
	},
	{
		"tax_name": "VAT",
		"calculation_type": "Percentage",
		"allowed_calculation_modes": CALC_MODE_PERCENTAGE,
		"default_calculation_mode": CALC_MODE_PERCENTAGE,
		"is_stacking": 1,
		"is_excise": 0,
		"affects_import_duty": 0,
		"feeds_running_base": 1,
		"per_unit_skips_running_base": 0,
	},
	{
		"tax_name": "IDF",
		"calculation_type": "Percentage",
		"allowed_calculation_modes": CALC_MODE_PERCENTAGE,
		"default_calculation_mode": CALC_MODE_PERCENTAGE,
		"is_stacking": 0,
		"is_excise": 0,
		"affects_import_duty": 1,
		"feeds_running_base": 1,
		"per_unit_skips_running_base": 0,
	},
	{
		"tax_name": "RDL",
		"calculation_type": "Percentage",
		"allowed_calculation_modes": CALC_MODE_PERCENTAGE,
		"default_calculation_mode": CALC_MODE_PERCENTAGE,
		"is_stacking": 0,
		"is_excise": 0,
		"affects_import_duty": 1,
		"feeds_running_base": 1,
		"per_unit_skips_running_base": 0,
	},
	{
		"tax_name": "Excise Duty",
		"calculation_type": "Percentage",
		"allowed_calculation_modes": f"{CALC_MODE_PERCENTAGE}\n{CALC_MODE_FIXED_AMOUNT}",
		"default_calculation_mode": CALC_MODE_PERCENTAGE,
		"is_stacking": 0,
		"is_excise": 1,
		"affects_import_duty": 0,
		"feeds_running_base": 1,
		"per_unit_skips_running_base": 0,
	},
	{
		"tax_name": "MSS Levy",
		"calculation_type": "Per Weight",
		"allowed_calculation_modes": f"{CALC_MODE_PERCENTAGE}\n{CALC_MODE_PER_UNIT}",
		"default_calculation_mode": CALC_MODE_PER_UNIT,
		"is_stacking": 0,
		"is_excise": 0,
		"affects_import_duty": 1,
		"feeds_running_base": 1,
		"per_unit_skips_running_base": 1,
	},
]

DEFAULT_CUSTOMS_TAX_RATES: dict[str, float] = {
	"VAT": 16,
	"IDF": 2.5,
	"RDL": 2,
}
