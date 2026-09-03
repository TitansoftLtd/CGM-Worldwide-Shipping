# Copyright (c) 2026, Titansoft Limited and contributors
# See license.txt

import unittest

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
	apply_batch_approve_to_pending_rows,
	funding_approval_is_recorded,
	funding_is_approved,
	funding_is_pending,
	funding_progress_state,
	get_material_request_item_summary,
	get_material_request_total,
	mr_workflow_state_from_funding_request,
	mr_row_workflow_state,
	material_request_purchase_is_funding_approved,
	variance_amount,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
	FundingWorkflowMap,
)


def _funding_workflow(states, transitions):
	return frappe._dict(
		states=[
			frappe._dict(state=name, doc_status=str(doc_status), idx=idx)
			for idx, (name, doc_status) in enumerate(states, start=1)
		],
		transitions=[
			frappe._dict(state=src, action=action, next_state=dst)
			for src, action, dst in transitions
		],
	)


# Mirrors the Desk Funding Request workflow: labels can change, the graph cannot.
USER_FUNDING_WORKFLOW = _funding_workflow(
	[
		("Draft", 0),
		("Pending", 0),
		("Approved", 1),
		("Partially Approved", 1),
		("Disbursement in Progress", 1),
		("Disbursed", 1),
		("Completed", 1),
		("Rejected", 0),
		("Cancelled", 2),
	],
	[
		("Draft", "Submit", "Pending"),
		("Rejected", "Submit", "Pending"),
		("Pending", "Approve", "Approved"),
		("Pending", "Reject", "Rejected"),
		("Disbursed", "Complete", "Completed"),
		("Approved", "Cancel", "Cancelled"),
		("Partially Approved", "Cancel", "Cancelled"),
		("Disbursement in Progress", "Cancel", "Cancelled"),
	],
)

# Server Material Request workflow labels (Pending, not Pending Approval).
SERVER_MR_STATES = frozenset(
	{
		"Draft",
		"Submitted",
		"Unfunded",
		"On Funding Request",
		"Pending",
		"Approved",
		"Partially Approved",
		"Disbursed",
		"Rejected",
		"Cancelled",
	}
)


class TestFundingRequestHelpers(unittest.TestCase):
	def test_variance_preserves_requested_amount(self):
		requested = 5000
		approved = 3500
		self.assertEqual(variance_amount(requested, approved), -1500)
		self.assertEqual(requested, 5000)
		self.assertEqual(approved, 3500)

	def test_invalid_material_request_link_is_rejected(self):
		from cgm_shipping.cgm_worldwide_shipping.doctype.funding_request.funding_request import (
			is_valid_funding_material_request_link,
		)

		self.assertFalse(is_valid_funding_material_request_link(None))
		self.assertFalse(is_valid_funding_material_request_link(""))
		self.assertFalse(is_valid_funding_material_request_link("Material Request"))
		self.assertTrue(is_valid_funding_material_request_link("MAT-MR-2026-00013"))

	def test_variance_amount_sign(self):
		self.assertEqual(variance_amount(5000, 3500), -1500)
		self.assertEqual(variance_amount(5000, 5500), 500)

	def test_full_approval_has_no_variance(self):
		self.assertEqual(variance_amount(2000, 2000), 0)

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

	def test_purchase_requester_uses_requested_by_when_no_employee(self):
		from unittest.mock import patch

		import frappe

		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			get_material_request_requester_name,
		)

		mr = frappe._dict(
			custom_employee=None,
			custom_requested_by="user@example.com",
			custom_requested_by_name="Jane Purchase",
		)
		self.assertEqual(get_material_request_requester_name(mr), "Jane Purchase")

		with patch(
			"frappe.db.get_value",
			return_value="Bob Employee",
		):
			mr_oe = frappe._dict(custom_employee="EMP-1")
			self.assertEqual(get_material_request_requester_name(mr_oe), "Bob Employee")

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

	def test_unapproved_funding_cannot_create_payment_docs(self):
		wf = USER_FUNDING_WORKFLOW
		self.assertFalse(funding_is_approved("Draft", 0, workflow=wf))
		self.assertFalse(funding_is_approved("Pending", 0, workflow=wf))
		self.assertFalse(funding_is_approved("Rejected", 0, workflow=wf))
		self.assertFalse(funding_is_approved("Approved", 0, workflow=wf))

	def test_operational_expense_uses_item_expense_account_then_settings_default(self):
		from unittest.mock import patch

		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			_company_bank_or_cash_account,
			_default_operational_expense_account,
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

		with patch("frappe.db.exists", return_value=True):
			with patch("frappe.db.has_column", return_value=True):
				with patch("frappe.db.get_single_value", return_value="Settings Expense - CWSCL"):
					with patch("frappe.db.get_value", side_effect=_not_group):
						self.assertEqual(
							_default_operational_expense_account("Company"),
							"Settings Expense - CWSCL",
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

	def test_total_approved_is_not_recorded_before_approver_approves(self):
		wf = USER_FUNDING_WORKFLOW
		self.assertFalse(funding_approval_is_recorded("Draft", workflow=wf))
		self.assertFalse(funding_approval_is_recorded("Pending", workflow=wf))
		self.assertFalse(funding_approval_is_recorded("Rejected", workflow=wf))
		self.assertTrue(funding_approval_is_recorded("Approved", workflow=wf))
		self.assertTrue(funding_approval_is_recorded("Partially Approved", workflow=wf))
		self.assertTrue(funding_approval_is_recorded("Disbursed", workflow=wf))

	def test_approved_funding_can_create_payment_docs(self):
		wf = USER_FUNDING_WORKFLOW
		self.assertTrue(funding_is_approved("Approved", 1, workflow=wf))
		self.assertTrue(funding_is_approved("Partially Approved", 1, workflow=wf))
		self.assertTrue(funding_is_approved("Disbursement in Progress", 1, workflow=wf))
		self.assertTrue(funding_is_approved("Disbursed", 1, workflow=wf))

	def test_submitting_journal_entry_does_not_revert_disbursement_in_progress(self):
		wf = USER_FUNDING_WORKFLOW
		self.assertEqual(
			funding_progress_state("Disbursement in Progress", 0, 700, workflow=wf),
			"Disbursement in Progress",
		)
		self.assertEqual(
			funding_progress_state("Approved", 0, 700, workflow=wf),
			"Approved",
		)
		self.assertEqual(
			funding_progress_state("Approved", 200, 700, workflow=wf),
			"Disbursement in Progress",
		)
		self.assertEqual(
			funding_progress_state("Disbursement in Progress", 700, 700, workflow=wf),
			"Disbursed",
		)
		self.assertEqual(
			funding_progress_state("Disbursed", 0, 700, workflow=wf),
			"Disbursement in Progress",
		)

	def test_rejected_is_never_approved(self):
		wf = USER_FUNDING_WORKFLOW
		self.assertFalse(funding_is_approved("Rejected", 1, workflow=wf))
		self.assertFalse(funding_is_approved("Cancelled", 2, workflow=wf))

	def test_purchase_documents_require_funding_approved(self):
		from unittest.mock import patch

		import frappe

		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			assert_material_request_may_create_purchase_document,
			material_request_purchase_is_funding_approved,
		)

		self.assertTrue(material_request_purchase_is_funding_approved(""))

		unfunded = frappe._dict(material_request_type="Purchase", custom_funding_request=None)
		with patch("frappe.db.get_value", return_value=unfunded):
			self.assertFalse(material_request_purchase_is_funding_approved("MAT-MR-1"))
			self.assertRaises(
				frappe.ValidationError,
				assert_material_request_may_create_purchase_document,
				"MAT-MR-1",
			)

		transfer = frappe._dict(
			material_request_type="Material Transfer", custom_funding_request=None
		)
		with patch("frappe.db.get_value", return_value=transfer):
			self.assertTrue(material_request_purchase_is_funding_approved("MAT-MR-2"))

		def _approved_lookup(doctype, name, fields, as_dict=False):
			if doctype == "Material Request":
				return frappe._dict(
					material_request_type="Purchase", custom_funding_request="FR-1"
				)
			return frappe._dict(workflow_state="Approved", docstatus=1)

		wf_map = FundingWorkflowMap.from_workflow(USER_FUNDING_WORKFLOW)
		with patch("frappe.db.get_value", side_effect=_approved_lookup):
			with patch(
				"cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_funding_workflow_map",
				return_value=wf_map,
			):
				self.assertTrue(material_request_purchase_is_funding_approved("MAT-MR-3"))
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

	def test_funding_request_maps_to_material_request_workflow_states(self):
		wf = USER_FUNDING_WORKFLOW
		mr = SERVER_MR_STATES
		self.assertEqual(
			mr_workflow_state_from_funding_request("Draft", workflow=wf, mr_workflow=mr),
			"On Funding Request",
		)
		self.assertEqual(
			mr_workflow_state_from_funding_request("Pending", workflow=wf, mr_workflow=mr),
			"Pending",
		)
		self.assertEqual(
			mr_workflow_state_from_funding_request("Approved", workflow=wf, mr_workflow=mr),
			"Approved",
		)
		self.assertEqual(
			mr_workflow_state_from_funding_request(
				"Partially Approved", workflow=wf, mr_workflow=mr
			),
			"Partially Approved",
		)
		self.assertEqual(
			mr_workflow_state_from_funding_request(
				"Disbursement in Progress", workflow=wf, mr_workflow=mr
			),
			"Approved",
		)
		self.assertEqual(
			mr_workflow_state_from_funding_request("Disbursed", workflow=wf, mr_workflow=mr),
			"Disbursed",
		)
		self.assertEqual(
			mr_workflow_state_from_funding_request("Completed", workflow=wf, mr_workflow=mr),
			"Disbursed",
		)
		self.assertEqual(
			mr_workflow_state_from_funding_request("Rejected", workflow=wf, mr_workflow=mr),
			"Rejected",
		)
		self.assertEqual(
			mr_workflow_state_from_funding_request(
				"Pending",
				workflow=wf,
				mr_workflow={"On Funding Request", "Pending Approval", "Approved", "Rejected"},
			),
			"Pending Approval",
		)

	def test_operational_expense_becomes_disbursed_when_that_request_is_paid(self):
		wf = USER_FUNDING_WORKFLOW
		mr = SERVER_MR_STATES
		self.assertEqual(
			mr_row_workflow_state(
				"Disbursement in Progress", 200, 0, workflow=wf, mr_workflow=mr
			),
			"Approved",
		)
		self.assertEqual(
			mr_row_workflow_state(
				"Disbursement in Progress", 200, 200, workflow=wf, mr_workflow=mr
			),
			"Disbursed",
		)
		self.assertEqual(
			mr_row_workflow_state("Approved", 200, 50, workflow=wf, mr_workflow=mr),
			"Approved",
		)

	def test_pending_is_read_from_the_workflow_graph(self):
		wf = USER_FUNDING_WORKFLOW
		self.assertTrue(funding_is_pending("Pending", workflow=wf))
		self.assertFalse(funding_is_pending("Pending Approval", workflow=wf))
		self.assertFalse(funding_is_pending("Draft", workflow=wf))
		self.assertFalse(funding_is_pending("Approved", workflow=wf))

		renamed = _funding_workflow(
			[
				("Draft", 0),
				("Queued", 0),
				("Greenlit", 1),
				("No", 0),
				("Stopped", 2),
			],
			[
				("Draft", "Submit", "Queued"),
				("Queued", "Approve", "Greenlit"),
				("Queued", "Reject", "No"),
				("Greenlit", "Cancel", "Stopped"),
			],
		)
		self.assertTrue(funding_is_pending("Queued", workflow=renamed))
		self.assertTrue(funding_approval_is_recorded("Greenlit", workflow=renamed))
		self.assertTrue(funding_is_approved("Greenlit", 1, workflow=renamed))
		self.assertEqual(
			mr_workflow_state_from_funding_request(
				"Queued", workflow=renamed, mr_workflow={"Queued", "Greenlit", "No"}
			),
			"Queued",
		)
		self.assertEqual(
			mr_workflow_state_from_funding_request(
				"Greenlit", workflow=renamed, mr_workflow={"Queued", "Greenlit", "No"}
			),
			"Greenlit",
		)

	def test_workflow_map_classifies_partial_and_disbursement_without_labels(self):
		wf_map = FundingWorkflowMap.from_workflow(USER_FUNDING_WORKFLOW)
		self.assertEqual(wf_map.pending_states, frozenset({"Pending"}))
		self.assertEqual(wf_map.approve_next_states, frozenset({"Approved"}))
		self.assertEqual(wf_map.reject_next_states, frozenset({"Rejected"}))
		self.assertEqual(wf_map.partial_state, "Partially Approved")
		self.assertEqual(wf_map.disbursement_state, "Disbursement in Progress")
		self.assertEqual(wf_map.complete_from_states, frozenset({"Disbursed"}))
		self.assertEqual(wf_map.complete_next_states, frozenset({"Completed"}))
		self.assertEqual(wf_map.cancel_state, "Cancelled")

	def test_header_approve_promotes_pending_rows(self):
		import frappe

		pending = frappe._dict(decision="Pending", approved_amount=0, requested_amount=1500)
		rejected = frappe._dict(decision="Rejected", approved_amount=0, requested_amount=800)
		already = frappe._dict(decision="Approved", approved_amount=1200, requested_amount=1500)
		apply_batch_approve_to_pending_rows([pending, rejected, already])
		self.assertEqual(pending.decision, "Approved")
		self.assertEqual(pending.approved_amount, 1500)
		self.assertEqual(rejected.decision, "Rejected")
		self.assertEqual(already.decision, "Approved")
		self.assertEqual(already.approved_amount, 1200)
