# Copyright (c) 2026, Titansoft Limited and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading import bill_of_lading
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

	def test_sync_opportunity_from_bl_updates_draft_bill_of_lading(self):
		class DummyMeta:
			def has_field(self, fieldname):
				return True

		class DummyOpportunity:
			def __init__(self):
				self.meta = DummyMeta()
				self.values = {}
				self.saved = False

			def get(self, fieldname):
				return self.values.get(fieldname)

			def set(self, fieldname, value):
				self.values[fieldname] = value

			def save(self, ignore_permissions=False):
				self.saved = True

		class DummyBL:
			def __init__(self):
				self.name = "BL-001"
				self.docstatus = 0
				self.meta = DummyMeta()
				self.values = {}

			def get(self, fieldname):
				return self.values.get(fieldname)

			def set(self, fieldname, value):
				self.values[fieldname] = value

			def _summarize_container_quantities(self):
				return "2 x 20FT"

		opp = DummyOpportunity()
		bl_doc = DummyBL()

		with patch.object(bill_of_lading, "resolve_opportunity_for_bl", return_value="OPP-001"), patch.object(
			bill_of_lading, "get_bl_config", return_value={
				"opportunity_bl_field": "custom_bill_of_lading",
				"opportunity_quantity_field": "custom_quantity",
				"opportunity_source_field": "linked_opportunity",
			}
		), patch.object(bill_of_lading, "get_opportunity_documents_field", return_value=None), patch.object(
			bill_of_lading, "apply_bl_fields_to_doc", return_value=True
		), patch.object(bill_of_lading.frappe, "get_doc", return_value=opp):
			result = bill_of_lading.sync_opportunity_from_bl(bl_doc, allow_draft=True)

		self.assertEqual(result, "OPP-001")
		self.assertTrue(opp.saved)
