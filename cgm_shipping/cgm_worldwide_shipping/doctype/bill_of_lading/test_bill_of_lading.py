# Copyright (c) 2026, Titansoft Limited and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import today

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	DEPOSIT_ARRANGEMENT_CONTAINER,
	DEPOSIT_ARRANGEMENT_REVOLVING,
	DEPOSIT_PAYMENT_STATUSES,
	DEPOSIT_REFUND_STATUSES,
)
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
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	BL_TO_OPPORTUNITY_DETAIL_FIELDS,
)
from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
	DEPOSIT_JE_KIND_OUTBOUND,
	amended_bill_of_lading_name,
	bl_is_refundable,
	build_bill_of_lading_name,
	ensure_bl_cargo_type,
	expand_requested_cargo_to_container_stubs,
	is_deposit_journal_entry,
	maybe_start_bl_deposit_refund_tracking,
	parse_batch_number_from_bl_name,
	refresh_bl_deposit_payment_status,
	rollup_bl_deposit_amount,
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


class TestBillOfLadingAmendedNaming(UnitTestCase):
	def test_amended_bill_of_lading_name_first_revision(self):
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.frappe.db.get_value",
			return_value=None,
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.frappe.db.exists",
			return_value=False,
		):
			name = amended_bill_of_lading_name("MB-0ONUJ", "MB-0ONUJ")
		self.assertEqual(name, "MB-0ONUJ-1")

	def test_amended_bill_of_lading_name_second_revision(self):
		with patch(
			"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.frappe.db.get_value",
			side_effect=["MB-0ONUJ", None],
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.frappe.db.exists",
			return_value=False,
		):
			name = amended_bill_of_lading_name("MB-0ONUJ", "MB-0ONUJ-1")
		self.assertEqual(name, "MB-0ONUJ-2")


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

	def test_fetch_container_rows_backfills_cargo_size_from_bl_quantity(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import fetch_container_rows

		with patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.frappe.db.exists",
			return_value=True,
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment._derived_quantity_for_bl_containers",
			return_value="2 x 20FT",
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.frappe.get_all",
			return_value=[
				{"container_number": "C1", "cargo_size": "", "seal_no": "S1"},
				{"container_number": "C2", "cargo_size": "", "seal_no": "S2"},
			],
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.get_container_fields",
			return_value=["container_number", "cargo_size", "seal_no"],
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.resolve_cargo_size_link",
			side_effect=lambda size: size,
		):
			rows = fetch_container_rows("BL-TEST")

		self.assertEqual([row["cargo_size"] for row in rows], ["20FT", "20FT"])


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


class TestBillOfLadingDeposits(IntegrationTestCase):
	def _bl(self, **kwargs):
		doc = frappe._dict(
			{
				"name": "BL-TEST",
				"deposit_arrangement": DEPOSIT_ARRANGEMENT_CONTAINER,
				"deposit_payer": "Customer",
				"deposit_amount": 0,
				"deposit_payment_journal_entry": None,
				"deposit_refund_status": None,
				"deposit_return_date": None,
				"container_information": [
					frappe._dict({"deposit_amount": 3000, "container_number": "C1"}),
					frappe._dict({"deposit_amount": 2000, "container_number": "C2"}),
					frappe._dict({"deposit_amount": 0, "container_number": "C3"}),
				],
			}
		)
		doc.update(kwargs)
		doc.meta = frappe.get_meta("Bill of Lading")
		return doc

	def test_rollup_bl_deposit_amount(self):
		bl = self._bl()
		self.assertEqual(rollup_bl_deposit_amount(bl), 5000)

	def test_bl_is_refundable_customer_not_agent(self):
		bl = self._bl(deposit_payer="Customer")
		self.assertTrue(bl_is_refundable(bl))
		bl.deposit_payer = "Agent"
		self.assertFalse(bl_is_refundable(bl))

	def test_refresh_bl_deposit_payment_status_not_applicable(self):
		bl = self._bl(
			deposit_arrangement=DEPOSIT_ARRANGEMENT_REVOLVING,
			container_information=[],
		)
		refresh_bl_deposit_payment_status(bl)
		self.assertEqual(bl.deposit_payment_status, DEPOSIT_PAYMENT_STATUSES[0])
		self.assertEqual(flt_or_zero(bl.deposit_amount), 0)

	def test_refresh_bl_deposit_payment_status_unpaid_without_je(self):
		bl = self._bl()
		refresh_bl_deposit_payment_status(bl)
		self.assertEqual(bl.deposit_payment_status, DEPOSIT_PAYMENT_STATUSES[1])
		self.assertEqual(flt_or_zero(bl.deposit_amount), 5000)

	def test_refresh_bl_deposit_payment_status_paid_with_submitted_je(self):
		if not frappe.db.exists("Journal Entry", {"docstatus": 1}):
			self.skipTest("No submitted Journal Entry on site")
		je_name = frappe.db.get_value("Journal Entry", {"docstatus": 1}, "name")
		bl = self._bl(deposit_payment_journal_entry=je_name)
		refresh_bl_deposit_payment_status(bl)
		self.assertEqual(bl.deposit_payment_status, DEPOSIT_PAYMENT_STATUSES[2])

	def test_refresh_bl_deposit_payment_status_unpaid_with_draft_je(self):
		if not frappe.db.exists("Journal Entry", {"docstatus": 0}):
			self.skipTest("No draft Journal Entry on site")
		je_name = frappe.db.get_value("Journal Entry", {"docstatus": 0}, "name")
		bl = self._bl(deposit_payment_journal_entry=je_name)
		refresh_bl_deposit_payment_status(bl)
		self.assertEqual(bl.deposit_payment_status, DEPOSIT_PAYMENT_STATUSES[1])

	def test_maybe_start_bl_deposit_refund_tracking_when_all_returned(self):
		bl = self._bl(
			deposit_payment_status=DEPOSIT_PAYMENT_STATUSES[2],
			deposit_payer="Customer",
			name="BL-REFUND-TEST",
		)
		from unittest.mock import patch

		with patch(
			"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.bl_all_containers_returned",
			return_value=(True, str(today())),
		):
			maybe_start_bl_deposit_refund_tracking(bl)
		self.assertEqual(bl.deposit_refund_status, DEPOSIT_REFUND_STATUSES[0])
		if bl.meta.has_field("deposit_return_date"):
			self.assertEqual(str(bl.deposit_return_date), str(today()))

	def test_maybe_start_bl_deposit_refund_tracking_skips_agent(self):
		bl = self._bl(
			deposit_payment_status=DEPOSIT_PAYMENT_STATUSES[2],
			deposit_payer="Agent",
		)
		maybe_start_bl_deposit_refund_tracking(bl)
		self.assertFalse(bl.deposit_refund_status)

	def test_maybe_start_bl_deposit_refund_tracking_skips_revolving_fund(self):
		bl = self._bl(
			deposit_arrangement=DEPOSIT_ARRANGEMENT_REVOLVING,
			deposit_payment_status=DEPOSIT_PAYMENT_STATUSES[2],
			container_information=[],
		)
		maybe_start_bl_deposit_refund_tracking(bl)
		self.assertFalse(bl.deposit_refund_status)

	def test_is_deposit_journal_entry_by_kind(self):
		je = frappe._dict({"custom_cgm_deposit_entry_kind": DEPOSIT_JE_KIND_OUTBOUND})
		je.meta = frappe.get_meta("Journal Entry")
		self.assertTrue(is_deposit_journal_entry(je))

	def test_is_deposit_journal_entry_by_bl_link(self):
		je = frappe._dict(
			{
				"custom_cgm_deposit_entry_kind": "",
				"custom_cgm_source_bill_of_lading": "BL-TEST",
				"custom_cgm_source_container_tracker": "",
			}
		)
		je.meta = frappe.get_meta("Journal Entry")
		self.assertTrue(is_deposit_journal_entry(je))

	def test_is_deposit_journal_entry_false_for_normal(self):
		je = frappe._dict(
			{
				"custom_cgm_deposit_entry_kind": "",
				"custom_cgm_source_container_tracker": "",
				"custom_cgm_source_bill_of_lading": "",
			}
		)
		je.meta = frappe.get_meta("Journal Entry")
		self.assertFalse(is_deposit_journal_entry(je))


def flt_or_zero(value):
	from frappe.utils import flt

	return flt(value)
