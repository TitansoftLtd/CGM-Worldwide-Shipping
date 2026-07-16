# Copyright (c) 2026, Titansoft Limited and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch import (
	counts_from_container_rows,
	counts_from_request_rows,
	format_derived_quantity,
	is_fcl_cargo_type,
	is_lcl_cargo_type,
	next_fcl_batch_number,
)
from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
	build_bill_of_lading_name,
	parse_batch_number_from_bl_name,
)


class TestFclBatchQuantity(IntegrationTestCase):
	def test_format_derived_quantity_canonical(self):
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch._cargo_size_display_order",
			return_value=["20FT", "40FT"],
		):
			self.assertEqual(
				format_derived_quantity({"40FT": 1, "20FT": 2}),
				"2 x 20FT, 1 x 40FT",
			)

	def test_request_and_container_rows_match(self):
		request_counts = counts_from_request_rows(
			[{"cargo_size": "20FT", "quantity": "2"}, {"cargo_size": "40FT", "quantity": 1}]
		)
		container_counts = counts_from_container_rows(
			[
				{"cargo_size": "20FT"},
				{"cargo_size": "20FT"},
				{"cargo_size": "40FT"},
			]
		)
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch._cargo_size_display_order",
			return_value=["20FT", "40FT"],
		):
			self.assertEqual(
				format_derived_quantity(request_counts),
				format_derived_quantity(container_counts),
			)

	def test_fcl_lcl_helpers(self):
		self.assertTrue(is_fcl_cargo_type("FCL"))
		self.assertTrue(is_lcl_cargo_type("lcl"))
		self.assertFalse(is_fcl_cargo_type("LCL"))

	def test_next_fcl_batch_uses_max_plus_one(self):
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch.lock_customer_for_fcl_batch"
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch._max_batch_from_doctype",
			side_effect=[2, 1],
		):
			self.assertEqual(
				next_fcl_batch_number(
					customer="CUST-A",
					shipment_type="Sea Import",
					derived_quantity="1 x 40FT",
				),
				3,
			)


class TestBillOfLadingNaming(IntegrationTestCase):
	def test_build_bill_of_lading_name_uses_bl_number_only(self):
		self.assertEqual(build_bill_of_lading_name("MB-0ONUJ", "2 x 20FT", 10), "MB-0ONUJ")
		self.assertEqual(build_bill_of_lading_name("MB-0ONUJ", "", 3), "MB-0ONUJ")
		self.assertEqual(
			build_bill_of_lading_name("234567890", "10 Cartons", None),
			"234567890",
		)

	def test_parse_batch_number_from_legacy_bl_name(self):
		self.assertEqual(parse_batch_number_from_bl_name("MB-0ONUJ 2 x 20FT-10"), 10)
		self.assertEqual(parse_batch_number_from_bl_name("MB-0ONUJ"), None)
		self.assertEqual(parse_batch_number_from_bl_name("MB-0ONUJ-7"), 7)
