# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.customs_tax_calculation import (
	CALC_MODE_FIXED_AMOUNT,
	CALC_MODE_PERCENTAGE,
	CALC_MODE_PER_UNIT,
	allowed_modes_for_tax,
	calculate_tax_amount,
	default_mode_for_tax,
	get_tax_type_config,
	import_duty_contribution,
	is_volume_uom,
	resolve_calculation_mode,
	should_feed_running_base,
	validate_calculation_mode,
)


class TestCustomsTaxCalculation(IntegrationTestCase):
	TEST_TAX_TYPE = "CGM Test Environmental Levy"

	def setUp(self):
		self._created_tax_types: list[str] = []

	def tearDown(self):
		for tax_type in self._created_tax_types:
			if frappe.db.exists("Customs Tax Type", tax_type):
				frappe.delete_doc("Customs Tax Type", tax_type, force=1)
		frappe.db.commit()

	def _create_tax_type(self, tax_name: str, **values) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Customs Tax Type",
				"tax_name": tax_name,
				"calculation_type": "Percentage",
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
			allowed_calculation_modes=f"{CALC_MODE_PERCENTAGE}\n{CALC_MODE_FIXED_AMOUNT}",
			default_calculation_mode=CALC_MODE_FIXED_AMOUNT,
			is_stacking=0,
			is_excise=0,
			affects_import_duty=0,
			feeds_running_base=1,
			per_unit_skips_running_base=0,
		)

		config = get_tax_type_config(tax_type)
		self.assertEqual(
			allowed_modes_for_tax(tax_type),
			(CALC_MODE_PERCENTAGE, CALC_MODE_FIXED_AMOUNT),
		)
		self.assertEqual(default_mode_for_tax(tax_type), CALC_MODE_FIXED_AMOUNT)
		self.assertFalse(config.is_excise)

		row = self._row(calculation_mode=CALC_MODE_FIXED_AMOUNT, fixed_amount_kes=12_500)
		amount = calculate_tax_amount(
			row,
			tax_type,
			customs_value_kes=400_000,
			running_base=400_000,
			import_duty_kes=0,
			shipment_qty=0,
		)
		self.assertEqual(amount, 12_500)
		self.assertEqual(import_duty_contribution(tax_type, CALC_MODE_FIXED_AMOUNT, amount), 0.0)

	def test_volume_uom_identified_via_uom_category(self):
		if not frappe.db.exists("UOM", "Litre"):
			self.skipTest("ERPNext UOM 'Litre' not installed")

		category = frappe.db.get_value("UOM", "Litre", "category")
		self.assertEqual(category, "Volume")
		self.assertTrue(is_volume_uom("Litre"))

	def test_incomplete_config_raises(self):
		tax_type = "CGM Test Incomplete Levy"
		# Bypass validate temporarily by inserting minimal then clearing modes via SQL
		self._create_tax_type(
			tax_type,
			allowed_calculation_modes=CALC_MODE_PERCENTAGE,
			default_calculation_mode=CALC_MODE_PERCENTAGE,
		)
		frappe.db.set_value(
			"Customs Tax Type",
			tax_type,
			{
				"allowed_calculation_modes": "",
				"default_calculation_mode": "",
			},
			update_modified=False,
		)
		frappe.clear_cache(doctype="Customs Tax Type")

		with self.assertRaises(frappe.ValidationError):
			get_tax_type_config(tax_type)

	def test_invalid_mode_raises(self):
		tax_type = "CGM Test Mode Guard Levy"
		self._create_tax_type(
			tax_type,
			allowed_calculation_modes=CALC_MODE_PERCENTAGE,
			default_calculation_mode=CALC_MODE_PERCENTAGE,
		)
		row = self._row(calculation_mode=CALC_MODE_FIXED_AMOUNT)
		with self.assertRaises(frappe.ValidationError):
			validate_calculation_mode(row, tax_type)

	def test_config_driven_excise_and_per_unit(self):
		excise = "CGM Test Excise"
		self._create_tax_type(
			excise,
			allowed_calculation_modes=f"{CALC_MODE_PERCENTAGE}\n{CALC_MODE_FIXED_AMOUNT}",
			default_calculation_mode=CALC_MODE_PERCENTAGE,
			is_excise=1,
			affects_import_duty=0,
			feeds_running_base=1,
		)
		excise_amount = calculate_tax_amount(
			self._row(rate=5),
			excise,
			customs_value_kes=400_000,
			running_base=400_000,
			import_duty_kes=40_000,
			shipment_qty=0,
		)
		self.assertEqual(excise_amount, 22_000)
		self.assertEqual(
			calculate_tax_amount(
				self._row(calculation_mode=CALC_MODE_FIXED_AMOUNT, rate=15_000),
				excise,
				customs_value_kes=400_000,
				running_base=400_000,
				import_duty_kes=40_000,
				shipment_qty=0,
			),
			15_000,
		)

		mss = "CGM Test Per Unit Levy"
		self._create_tax_type(
			mss,
			allowed_calculation_modes=f"{CALC_MODE_PERCENTAGE}\n{CALC_MODE_PER_UNIT}",
			default_calculation_mode=CALC_MODE_PER_UNIT,
			affects_import_duty=1,
			feeds_running_base=1,
			per_unit_skips_running_base=1,
		)
		mss_amount = calculate_tax_amount(
			self._row(calculation_mode=CALC_MODE_PER_UNIT, rate=50),
			mss,
			customs_value_kes=400_000,
			running_base=400_000,
			import_duty_kes=40_000,
			shipment_qty=10,
		)
		self.assertEqual(mss_amount, 500)
		self.assertFalse(should_feed_running_base(mss, CALC_MODE_PER_UNIT))

	def test_empty_mode_uses_default_without_rewriting_row(self):
		tax_type = "CGM Test Mode Default Levy"
		self._create_tax_type(
			tax_type,
			allowed_calculation_modes=f"{CALC_MODE_PERCENTAGE}\n{CALC_MODE_PER_UNIT}",
			default_calculation_mode=CALC_MODE_PER_UNIT,
			per_unit_skips_running_base=1,
		)
		row = self._row(calculation_mode="")
		self.assertEqual(resolve_calculation_mode(row, tax_type), CALC_MODE_PER_UNIT)
		self.assertEqual(row.calculation_mode, "")
