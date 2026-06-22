# Copyright (c) 2026, Titansoft Limited and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
	build_bill_of_lading_name,
	parse_batch_number_from_bl_name,
)


class TestBillOfLadingNaming(IntegrationTestCase):
	def test_build_bill_of_lading_name_with_quantity(self):
		self.assertEqual(
			build_bill_of_lading_name("MB-0ONUJ", "2 x 20FT", 10),
			"MB-0ONUJ 2 x 20FT-10",
		)

	def test_build_bill_of_lading_name_without_quantity(self):
		self.assertEqual(build_bill_of_lading_name("MB-0ONUJ", "", 3), "MB-0ONUJ-3")

	def test_parse_batch_number_from_bl_name(self):
		self.assertEqual(parse_batch_number_from_bl_name("MB-0ONUJ 2 x 20FT-10"), 10)
		self.assertEqual(parse_batch_number_from_bl_name("MB-0ONUJ"), None)
		self.assertEqual(parse_batch_number_from_bl_name("MB-0ONUJ-7"), 7)
