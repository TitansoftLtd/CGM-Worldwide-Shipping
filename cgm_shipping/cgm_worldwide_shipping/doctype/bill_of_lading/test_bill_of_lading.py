# Copyright (c) 2026, Titansoft Limited and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch import (
	AUTO_ALLOCATE_FCL_BATCH,
	allocate_fcl_batch_for_doc,
	counts_from_container_rows,
	counts_from_request_rows,
	format_derived_quantity,
	is_fcl_cargo_type,
	is_lcl_cargo_type,
	next_fcl_batch_number,
	normalize_derived_quantity,
)
from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
	build_bill_of_lading_name,
	ensure_bl_cargo_type,
	expand_requested_cargo_to_container_stubs,
	parse_batch_number_from_bl_name,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	BL_TO_OPPORTUNITY_DETAIL_FIELDS,
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
					derived_quantity="1 x 40FT",
				),
				3,
			)

	def test_normalize_derived_quantity_treats_size_variants_equally(self):
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch.normalize_cargo_size",
			side_effect=lambda size: (size or "").replace(" ", "").upper(),
		):
			left = normalize_derived_quantity("2 x 40 Ft")
			right = normalize_derived_quantity("2 x 40FT")
			self.assertEqual(left, right)
			self.assertEqual(left, "2 x 40FT")

	def test_allocate_fcl_batch_preserves_manual_entry(self):
		self.assertFalse(AUTO_ALLOCATE_FCL_BATCH)
		doc = frappe._dict(
			name="BK-TEST",
			customer="CUST-A",
			requested_cargo_type="FCL",
			batch_no="2123",
			quantity=None,
			meta=frappe._dict(
				has_field=lambda field, *_a, **_k: field
				in {"quantity", "batch_no", "requested_cargo_type"}
			),
		)
		doc.is_new = lambda: True
		result = allocate_fcl_batch_for_doc(
			doc,
			cargo_type_field="requested_cargo_type",
			derived_quantity="2 x 20FT",
		)
		self.assertIsNone(result)
		self.assertEqual(doc.batch_no, "2123")
		self.assertEqual(doc.quantity, "2 x 20FT")


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


class TestBillOfLadingBookingPrefill(IntegrationTestCase):
	def test_expand_requested_cargo_to_container_stubs(self):
		stubs = expand_requested_cargo_to_container_stubs(
			[
				{"cargo_size": "40FT", "quantity": "2"},
				{"cargo_size": "20FT", "quantity": 1},
			]
		)
		self.assertEqual(len(stubs), 3)
		self.assertEqual([s["cargo_size"] for s in stubs], ["40FT", "40FT", "20FT"])
		self.assertTrue(all(not s["container_number"] and not s["seal_no"] for s in stubs))

	def test_fill_missing_container_sizes_from_single_size_quantity(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch import (
			fill_missing_container_row_cargo_sizes,
		)

		rows = [
			{"container_number": "C1", "cargo_size": ""},
			{"container_number": "C2", "cargo_size": ""},
			{"container_number": "C3", "cargo_size": ""},
		]
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch.resolve_cargo_size_link",
			side_effect=lambda size: size,
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch.normalize_cargo_size",
			side_effect=lambda size: (size or "").replace(" ", "").upper(),
		):
			changed = fill_missing_container_row_cargo_sizes(rows, "3 x 20FT")
		self.assertTrue(changed)
		self.assertEqual([r["cargo_size"] for r in rows], ["20FT", "20FT", "20FT"])

	def test_fill_missing_container_sizes_mixed_only_when_all_blank(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch import (
			fill_missing_container_row_cargo_sizes,
		)

		rows = [
			{"container_number": "C1", "cargo_size": "20FT"},
			{"container_number": "C2", "cargo_size": ""},
			{"container_number": "C3", "cargo_size": ""},
		]
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch.resolve_cargo_size_link",
			side_effect=lambda size: size,
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch.normalize_cargo_size",
			side_effect=lambda size: (size or "").replace(" ", "").upper(),
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch._cargo_size_display_order",
			return_value=["20FT", "40FT"],
		):
			changed = fill_missing_container_row_cargo_sizes(rows, "2 x 20FT, 1 x 40FT")
		self.assertFalse(changed)
		self.assertEqual(rows[1]["cargo_size"], "")

	def test_bl_opportunity_maps_commodity_not_description(self):
		src_fields = {src for src, _dest in BL_TO_OPPORTUNITY_DETAIL_FIELDS}
		self.assertIn("commodity", src_fields)
		self.assertNotIn("description", src_fields)


class TestBillOfLadingCargoType(IntegrationTestCase):
	def test_ensure_bl_cargo_type_from_quantity(self):
		doc = frappe._dict(quantity="1 x 45FT", container_information=[])
		ensure_bl_cargo_type(doc)
		self.assertEqual(doc.cargo_type, "FCL")

	def test_ensure_bl_cargo_type_from_batch_no(self):
		doc = frappe._dict(batch_no="2123", container_information=[])
		ensure_bl_cargo_type(doc)
		self.assertEqual(doc.cargo_type, "FCL")

	def test_ensure_bl_cargo_type_from_packages(self):
		doc = frappe._dict(number_of_packages="10", package_type="Cartons")
		ensure_bl_cargo_type(doc)
		self.assertEqual(doc.cargo_type, "LCL")
