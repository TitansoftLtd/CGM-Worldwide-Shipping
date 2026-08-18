# Copyright (c) 2026, Titansoft Limited and contributors
# See license.txt

import unittest

from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
	NON_OE_WORKFLOW_CONDITION,
	OE_WORKFLOW_CONDITION,
	funding_approval_is_recorded,
	funding_is_approved,
	funding_progress_state,
	get_material_request_item_summary,
	get_material_request_total,
	mr_funding_state_for_funding_request,
	mr_row_funding_state,
	reduction_amount,
	with_operational_expense_request_type,
)


class TestFundingRequestHelpers(unittest.TestCase):
	def test_reduction_preserves_requested_amount(self):
		requested = 5000
		approved = 3500
		self.assertEqual(reduction_amount(requested, approved), 1500)
		self.assertEqual(requested, 5000)
		self.assertEqual(approved, 3500)

	def test_full_approval_has_no_reduction(self):
		self.assertEqual(reduction_amount(2000, 2000), 0)

	def test_requested_total_comes_from_items_not_header(self):
		import frappe

		mr = frappe._dict(
			items=[
				frappe._dict(amount=2000),
				frappe._dict(amount=1000),
				frappe._dict(amount=800),
			],
			custom_requested_amount=1,
		)
		self.assertEqual(get_material_request_total(mr), 3800)

	def test_legacy_header_amount_used_only_when_items_are_empty(self):
		import frappe

		mr = frappe._dict(items=[], custom_requested_amount=2000)
		self.assertEqual(get_material_request_total(mr), 2000)

	def test_item_summary_uses_item_names(self):
		import frappe

		mr = frappe._dict(
			items=[
				frappe._dict(item_code="TE", item_name="Transport Expense", amount=2000),
				frappe._dict(item_code="DC", item_name="Document Collection Expense", amount=1000),
			]
		)
		self.assertEqual(
			get_material_request_item_summary(mr),
			"Transport Expense, Document Collection Expense",
		)

	def test_unapproved_funding_cannot_create_advance(self):
		self.assertFalse(funding_is_approved("Draft", 0))
		self.assertFalse(funding_is_approved("Pending Director Approval", 0))
		self.assertFalse(funding_is_approved("Rejected", 0))
		self.assertFalse(funding_is_approved("Director Approved", 0))

	def test_operational_expense_uses_item_expense_account_then_transport_expense(self):
		from unittest.mock import patch

		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			_company_bank_or_cash_account,
			_material_request_expense_account,
		)

		def _not_group(doctype, name, field=None, as_dict=False):
			if field == "is_group":
				return 0
			return None

		with patch("frappe.get_all", return_value=["Felix Gor - CWSCL", None]):
			with patch("frappe.db.get_value", side_effect=_not_group):
				self.assertEqual(
					_material_request_expense_account("MAT-MR-1", "Company"),
					"Felix Gor - CWSCL",
				)

		def _company_bank(doctype, name, field=None, as_dict=False):
			if field == "default_bank_account":
				return "Stanbic Bank - CWSCL"
			return None

		with patch("frappe.db.get_value", side_effect=_company_bank):
			self.assertEqual(
				_company_bank_or_cash_account("Company"),
				"Stanbic Bank - CWSCL",
			)

	def test_total_approved_is_not_recorded_before_director_approves(self):
		self.assertFalse(funding_approval_is_recorded("Draft"))
		self.assertFalse(funding_approval_is_recorded("Pending Director Approval"))
		self.assertFalse(funding_approval_is_recorded("Rejected"))
		self.assertTrue(funding_approval_is_recorded("Director Approved"))
		self.assertTrue(funding_approval_is_recorded("Funded"))

	def test_approved_funding_can_create_advance(self):
		self.assertTrue(funding_is_approved("Director Approved", 1))
		self.assertTrue(funding_is_approved("Funding in Progress", 1))
		self.assertTrue(funding_is_approved("Funded", 1))

	def test_submitting_employee_advance_does_not_revert_funding_in_progress(self):
		self.assertEqual(
			funding_progress_state("Funding in Progress", 0, 700),
			"Funding in Progress",
		)
		self.assertEqual(
			funding_progress_state("Director Approved", 0, 700),
			"Director Approved",
		)
		self.assertEqual(
			funding_progress_state("Director Approved", 200, 700),
			"Funding in Progress",
		)
		self.assertEqual(
			funding_progress_state("Funding in Progress", 700, 700),
			"Funded",
		)
		self.assertEqual(
			funding_progress_state("Funded", 0, 700),
			"Funding in Progress",
		)

	def test_rejected_is_never_approved(self):
		self.assertFalse(funding_is_approved("Rejected", 1))
		self.assertFalse(funding_is_approved("Cancelled", 2))

	def test_purchase_documents_require_director_approved_funding(self):
		from unittest.mock import patch

		import frappe

		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			assert_material_request_may_create_purchase_document,
			material_request_purchase_is_director_approved,
		)

		self.assertTrue(material_request_purchase_is_director_approved(""))

		unfunded = frappe._dict(material_request_type="Purchase", custom_funding_request=None)
		with patch("frappe.db.get_value", return_value=unfunded):
			self.assertFalse(material_request_purchase_is_director_approved("MAT-MR-1"))
			self.assertRaises(
				frappe.ValidationError,
				assert_material_request_may_create_purchase_document,
				"MAT-MR-1",
			)

		transfer = frappe._dict(
			material_request_type="Material Transfer", custom_funding_request=None
		)
		with patch("frappe.db.get_value", return_value=transfer):
			self.assertTrue(material_request_purchase_is_director_approved("MAT-MR-2"))

		def _approved_lookup(doctype, name, fields, as_dict=False):
			if doctype == "Material Request":
				return frappe._dict(
					material_request_type="Purchase", custom_funding_request="FR-1"
				)
			return frappe._dict(workflow_state="Director Approved", docstatus=1)

		with patch("frappe.db.get_value", side_effect=_approved_lookup):
			self.assertTrue(material_request_purchase_is_director_approved("MAT-MR-3"))
			assert_material_request_may_create_purchase_document("MAT-MR-3")

	def test_purchase_order_keeps_required_by_when_material_request_date_is_past(self):
		import frappe
		from frappe.utils import add_days, nowdate

		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			_ensure_purchase_order_required_by,
		)

		yesterday = add_days(nowdate(), -1)
		po = frappe._dict(
			schedule_date=None,
			items=[frappe._dict(schedule_date=yesterday), frappe._dict(schedule_date=None)],
		)
		_ensure_purchase_order_required_by(po)
		self.assertEqual(po.schedule_date, nowdate())
		self.assertEqual(po.get("items")[0].schedule_date, nowdate())
		self.assertEqual(po.get("items")[1].schedule_date, nowdate())

	def test_hooks_are_wired(self):
		import frappe

		events = frappe.get_hooks("doc_events")
		mr_validate = events.get("Material Request", {}).get("validate") or []
		if isinstance(mr_validate, str):
			mr_validate = [mr_validate]
		self.assertTrue(
			any("funding.on_material_request_validate" in h for h in mr_validate),
			"Material Request validate hook is missing",
		)
		mr_submit = events.get("Material Request", {}).get("on_submit") or []
		if isinstance(mr_submit, str):
			mr_submit = [mr_submit]
		self.assertTrue(
			any("funding.on_material_request_on_submit" in h for h in mr_submit),
			"Material Request on_submit hook is missing",
		)
		je_submit = events.get("Journal Entry", {}).get("on_submit") or []
		if isinstance(je_submit, str):
			je_submit = [je_submit]
		self.assertTrue(
			any("funding.on_journal_entry_on_submit" in h for h in je_submit),
			"Journal Entry on_submit funding hook is missing",
		)
		for doctype in ("Purchase Order", "Request for Quotation", "Supplier Quotation"):
			validates = events.get(doctype, {}).get("validate") or []
			if isinstance(validates, str):
				validates = [validates]
			self.assertTrue(
				any("funding.on_purchase_document_validate" in h for h in validates),
				f"{doctype} validate hook is missing",
			)
		pe_submit = events.get("Payment Entry", {}).get("on_submit") or []
		if isinstance(pe_submit, str):
			pe_submit = [pe_submit]
		self.assertTrue(
			any("funding.on_payment_entry_on_submit" in h for h in pe_submit),
			"Payment Entry on_submit hook is missing",
		)

	def test_operational_expense_is_appended_without_replacing_erpnext_types(self):
		erpnext_options = "Purchase\nMaterial Transfer\nMaterial Issue"
		merged = with_operational_expense_request_type(erpnext_options).split("\n")
		self.assertEqual(merged[:3], erpnext_options.split("\n"))
		self.assertEqual(merged[-1], "Operational Expense")
		self.assertEqual(merged.count("Operational Expense"), 1)
		self.assertEqual(
			with_operational_expense_request_type("\n".join(merged)),
			"\n".join(merged),
		)

	def test_funding_request_maps_to_material_request_workflow_states(self):
		self.assertEqual(
			mr_funding_state_for_funding_request("Draft"), "On Funding Request"
		)
		self.assertEqual(
			mr_funding_state_for_funding_request("Pending Director Approval"),
			"Pending Director Approval",
		)
		self.assertEqual(
			mr_funding_state_for_funding_request("Director Approved"), "Director Approved"
		)
		self.assertEqual(
			mr_funding_state_for_funding_request("Funding in Progress"), "Director Approved"
		)
		self.assertEqual(mr_funding_state_for_funding_request("Funded"), "Funded")
		self.assertEqual(mr_funding_state_for_funding_request("Completed"), "Funded")
		self.assertEqual(mr_funding_state_for_funding_request("Rejected"), "Rejected")

	def test_operational_expense_becomes_funded_when_that_request_is_paid(self):
		self.assertEqual(
			mr_row_funding_state("Funding in Progress", 200, 0),
			"Director Approved",
		)
		self.assertEqual(
			mr_row_funding_state("Funding in Progress", 200, 200),
			"Funded",
		)
		self.assertEqual(
			mr_row_funding_state("Director Approved", 200, 50),
			"Director Approved",
		)

	def test_material_request_submit_paths_are_split_by_request_type(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			_mr_funding_workflow_transitions,
		)

		self.assertIn("Operational Expense", OE_WORKFLOW_CONDITION)
		self.assertIn("Operational Expense", NON_OE_WORKFLOW_CONDITION)
		self.assertIn("==", OE_WORKFLOW_CONDITION)
		self.assertIn("!=", NON_OE_WORKFLOW_CONDITION)

		actions = {(row["action"], row["next_state"]) for row in _mr_funding_workflow_transitions()}
		self.assertIn(("Submit", "Submitted"), actions)
		self.assertIn(("Submit Request", "Unfunded"), actions)
		self.assertIn(("Cancel", "Cancelled"), actions)

	def test_funding_workflow_does_not_let_finance_mark_funded_before_payment(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			_funding_workflow_transitions,
		)

		actions = {(row["action"], row["next_state"]) for row in _funding_workflow_transitions()}
		self.assertNotIn(("Mark Funded", "Funded"), actions)
		self.assertNotIn(("Start Funding", "Funding in Progress"), actions)
		self.assertIn(("Complete", "Completed"), actions)
