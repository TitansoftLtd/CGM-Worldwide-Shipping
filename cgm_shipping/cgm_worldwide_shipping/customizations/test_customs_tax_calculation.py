# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	CALC_MODE_FIXED_AMOUNT,
	CALC_MODE_PERCENTAGE,
	CALC_MODE_PER_UNIT,
	PERCENTAGE_BASE_CUSTOMS_VALUE,
	PERCENTAGE_BASE_RUNNING_TAX_BASE,
	allowed_modes_for_tax,
	calculate_tax_amount,
	default_mode_for_tax,
	format_rate_display,
	get_tax_type_config,
	is_volume_uom,
	normalize_percentage_base,
	resolve_calculation_mode,
	should_include_in_subsequent_tax_base,
	validate_calculation_mode,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_type_seed_data import (
	CUSTOMS_CALCULATION_MODES,
)


class TestCustomsTaxCalculation(IntegrationTestCase):
	TEST_TAX_TYPE = "CGM Test Environmental Levy"

	def setUp(self):
		self._created_tax_types: list[str] = []
		self._ensure_calculation_modes()

	def tearDown(self):
		for tax_type in self._created_tax_types:
			if frappe.db.exists("Customs Tax Type", tax_type):
				frappe.delete_doc("Customs Tax Type", tax_type, force=1)
		frappe.db.commit()

	def _ensure_calculation_modes(self) -> None:
		for row in CUSTOMS_CALCULATION_MODES:
			name = row["mode_name"]
			if frappe.db.exists("Customs Calculation Mode", name):
				continue
			frappe.get_doc({"doctype": "Customs Calculation Mode", **row}).insert(
				ignore_permissions=True
			)
		frappe.db.commit()

	def _create_tax_type(self, tax_name: str, **values) -> None:
		modes = values.pop("allowed_calculation_modes", None)
		if isinstance(modes, str):
			mode_list = [m.strip() for m in modes.splitlines() if m.strip()]
		elif isinstance(modes, (list, tuple)):
			mode_list = []
			for item in modes:
				if isinstance(item, dict):
					mode_list.append(item["calculation_mode"])
				else:
					mode_list.append(item)
		else:
			mode_list = [CALC_MODE_PERCENTAGE]

		doc = frappe.get_doc(
			{
				"doctype": "Customs Tax Type",
				"tax_name": tax_name,
				"percentage_base": values.pop("percentage_base", PERCENTAGE_BASE_CUSTOMS_VALUE),
				"include_in_subsequent_tax_base": values.pop(
					"include_in_subsequent_tax_base", 0
				),
				"default_calculation_mode": values.pop(
					"default_calculation_mode", mode_list[0]
				),
				"allowed_calculation_modes": [
					{"calculation_mode": mode} for mode in mode_list
				],
				**values,
			}
		)
		doc.insert(ignore_permissions=True)
		self._created_tax_types.append(tax_name)
		frappe.clear_cache(doctype="Customs Tax Type")
		frappe.db.commit()

	def _row(self, **kwargs):
		defaults = {
			"calculation_mode": CALC_MODE_PERCENTAGE,
			"rate": 10,
			"fixed_amount_kes": 0,
		}
		defaults.update(kwargs)
		return frappe._dict(defaults)

	def test_new_tax_type_via_config_without_code_change(self):
		tax_type = self.TEST_TAX_TYPE
		self._create_tax_type(
			tax_type,
			allowed_calculation_modes=[CALC_MODE_PERCENTAGE, CALC_MODE_FIXED_AMOUNT],
			default_calculation_mode=CALC_MODE_FIXED_AMOUNT,
			percentage_base=PERCENTAGE_BASE_CUSTOMS_VALUE,
			include_in_subsequent_tax_base=0,
		)

		config = get_tax_type_config(tax_type)
		self.assertEqual(
			allowed_modes_for_tax(tax_type),
			(CALC_MODE_PERCENTAGE, CALC_MODE_FIXED_AMOUNT),
		)
		self.assertEqual(default_mode_for_tax(tax_type), CALC_MODE_FIXED_AMOUNT)
		self.assertEqual(config.percentage_base, PERCENTAGE_BASE_CUSTOMS_VALUE)
		self.assertFalse(config.include_in_subsequent_tax_base)

		row = self._row(
			calculation_mode=CALC_MODE_FIXED_AMOUNT,
			rate=12_500,
			fixed_amount_kes=12_500,
		)
		result = calculate_tax_amount(
			row,
			tax_type,
			customs_value=400_000,
			running_tax_base=400_000,
			shipment_qty=0,
		)
		self.assertEqual(result.amount, 12_500)
		self.assertEqual(result.tax_base, 0.0)
		self.assertFalse(should_include_in_subsequent_tax_base(tax_type))

	def test_volume_uom_identified_via_uom_category(self):
		if not frappe.db.exists("UOM", "Litre"):
			self.skipTest("ERPNext UOM 'Litre' not installed")

		category = frappe.db.get_value("UOM", "Litre", "category")
		self.assertEqual(category, "Volume")
		self.assertTrue(is_volume_uom("Litre"))

	def test_incomplete_config_raises(self):
		tax_type = "CGM Test Incomplete Levy"
		self._create_tax_type(
			tax_type,
			allowed_calculation_modes=[CALC_MODE_PERCENTAGE],
			default_calculation_mode=CALC_MODE_PERCENTAGE,
		)
		frappe.db.delete(
			"Customs Tax Allowed Mode",
			{"parent": tax_type, "parenttype": "Customs Tax Type"},
		)
		frappe.db.set_value(
			"Customs Tax Type",
			tax_type,
			{"default_calculation_mode": ""},
			update_modified=False,
		)
		frappe.clear_cache(doctype="Customs Tax Type")

		with self.assertRaises(frappe.ValidationError):
			get_tax_type_config(tax_type)

	def test_invalid_mode_raises(self):
		tax_type = "CGM Test Mode Guard Levy"
		self._create_tax_type(
			tax_type,
			allowed_calculation_modes=[CALC_MODE_PERCENTAGE],
			default_calculation_mode=CALC_MODE_PERCENTAGE,
		)
		row = self._row(calculation_mode=CALC_MODE_FIXED_AMOUNT)
		with self.assertRaises(frappe.ValidationError):
			validate_calculation_mode(row, tax_type)

	def test_running_tax_base_and_per_unit(self):
		excise = "CGM Test Excise"
		self._create_tax_type(
			excise,
			allowed_calculation_modes=[CALC_MODE_PERCENTAGE, CALC_MODE_FIXED_AMOUNT],
			default_calculation_mode=CALC_MODE_PERCENTAGE,
			percentage_base=PERCENTAGE_BASE_RUNNING_TAX_BASE,
			include_in_subsequent_tax_base=1,
		)
		excise_result = calculate_tax_amount(
			self._row(rate=5),
			excise,
			customs_value=400_000,
			running_tax_base=440_000,
			shipment_qty=0,
		)
		self.assertEqual(excise_result.amount, 22_000)
		self.assertEqual(excise_result.tax_base, 440_000)
		self.assertTrue(should_include_in_subsequent_tax_base(excise))

		self.assertEqual(
			calculate_tax_amount(
				self._row(calculation_mode=CALC_MODE_FIXED_AMOUNT, rate=15_000),
				excise,
				customs_value=400_000,
				running_tax_base=440_000,
				shipment_qty=0,
			).amount,
			15_000,
		)

		mss = "CGM Test Per Unit Levy"
		self._create_tax_type(
			mss,
			allowed_calculation_modes=[CALC_MODE_PERCENTAGE, CALC_MODE_PER_UNIT],
			default_calculation_mode=CALC_MODE_PER_UNIT,
			include_in_subsequent_tax_base=0,
		)
		mss_result = calculate_tax_amount(
			self._row(calculation_mode=CALC_MODE_PER_UNIT, rate=50),
			mss,
			customs_value=400_000,
			running_tax_base=440_000,
			shipment_qty=10,
		)
		self.assertEqual(mss_result.amount, 500)
		self.assertEqual(mss_result.tax_base, 10)
		self.assertFalse(should_include_in_subsequent_tax_base(mss))

	def test_customs_value_base(self):
		duty = "CGM Test Duty"
		self._create_tax_type(
			duty,
			allowed_calculation_modes=[CALC_MODE_PERCENTAGE],
			default_calculation_mode=CALC_MODE_PERCENTAGE,
			percentage_base=PERCENTAGE_BASE_CUSTOMS_VALUE,
			include_in_subsequent_tax_base=1,
		)
		result = calculate_tax_amount(
			self._row(rate=25),
			duty,
			customs_value=400_000,
			running_tax_base=500_000,
			shipment_qty=0,
		)
		self.assertEqual(result.amount, 100_000)
		self.assertEqual(result.tax_base, 400_000)

	def test_legacy_percentage_base_normalized(self):
		self.assertEqual(
			normalize_percentage_base("Cumulative Base"),
			PERCENTAGE_BASE_RUNNING_TAX_BASE,
		)
		self.assertEqual(
			normalize_percentage_base("Customs Value + Duty Pool"),
			PERCENTAGE_BASE_RUNNING_TAX_BASE,
		)
		self.assertEqual(
			normalize_percentage_base(PERCENTAGE_BASE_CUSTOMS_VALUE),
			PERCENTAGE_BASE_CUSTOMS_VALUE,
		)

	def test_rate_display_formatting(self):
		self.assertEqual(format_rate_display(CALC_MODE_PERCENTAGE, 25), "25%")
		self.assertEqual(
			format_rate_display(CALC_MODE_FIXED_AMOUNT, 250, currency="KES"),
			"KES 250",
		)
		self.assertEqual(
			format_rate_display(
				CALC_MODE_PER_UNIT, 10, quotation_uom="Litre", currency="KES"
			),
			"KES 10 / Litre",
		)

	def test_empty_mode_uses_default_without_rewriting_row(self):
		tax_type = "CGM Test Mode Default Levy"
		self._create_tax_type(
			tax_type,
			allowed_calculation_modes=[CALC_MODE_PERCENTAGE, CALC_MODE_PER_UNIT],
			default_calculation_mode=CALC_MODE_PER_UNIT,
			include_in_subsequent_tax_base=0,
		)
		row = self._row(calculation_mode="")
		self.assertEqual(resolve_calculation_mode(row, tax_type), CALC_MODE_PER_UNIT)
		self.assertEqual(row.calculation_mode, "")
