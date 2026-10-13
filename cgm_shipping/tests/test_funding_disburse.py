"""Disbursing a Funding Request.

Rules pinned here:

* Disburse is the payment: every outstanding operational row gets a Journal
  Entry and that entry is submitted, not left as a draft.
* A draft raised earlier for a row is submitted as it stands. It is not
  duplicated, and its row is still offered for disbursing.
* It needs permission to submit a Journal Entry, not only to create one.
* A Completed request offers nothing and refuses payment documents, whatever
  its rows say. It used to show a payment action that could only fail.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import funding

OPERATIONAL = funding.MATERIAL_REQUEST_TYPE_OPERATIONAL


def _row(mr="MR-1", currency="KES", approved=1000, funded=0):
	return frappe._dict(
		material_request=mr,
		currency=currency,
		approved_amount=approved,
		funded_amount=funded,
		decision=funding.FR_ROW_DECISION_APPROVED,
		employee=None,
		employee_name=None,
		item_summary="",
	)


def _fr(rows, state="Approved"):
	return frappe._dict(
		name="FR-1", company="CGM", docstatus=1, workflow_state=state, material_requests=rows
	)


class TestDisburse(unittest.TestCase):
	def _run(self, rows, *, drafts=None, can_submit=True):
		drafts = drafts or {}
		built, submitted = [], []

		def build(fr, row, chosen):
			je = MagicMock()
			je.name = f"NEW-{row.material_request}"
			je.submit.side_effect = lambda: submitted.append(je.name)
			built.append(je.name)
			return je

		def get_doc(doctype, name):
			if doctype == "Funding Request":
				return _fr(rows)
			je = MagicMock()
			je.name = name
			je.submit.side_effect = lambda: submitted.append(name)
			return je

		def has_permission(doctype, ptype, throw=False):
			if ptype == "submit" and not can_submit:
				raise frappe.PermissionError
			return True

		with (
			patch.object(frappe, "has_permission", has_permission),
			patch.object(frappe, "get_doc", get_doc),
			patch.object(funding, "_assert_funding_request_approved"),
			patch.object(funding, "_outstanding_rows", return_value=rows),
			patch.object(funding, "_draft_journal_entry", side_effect=lambda fr, mr, cur=None: drafts.get(mr)),
			patch.object(funding, "_build_operational_journal_entry", build),
			patch.object(funding, "sync_funding_request_paid_amounts") as sync,
			patch.object(frappe.db, "get_value", return_value="Disbursed"),
		):
			result = funding.disburse_funding_request("FR-1", '{"KES": "Bank - C"}')
		return result, built, submitted, sync

	def test_every_outstanding_row_is_created_and_submitted(self):
		result, built, submitted, sync = self._run([_row("MR-1"), _row("MR-2", "USD")])
		self.assertEqual(built, ["NEW-MR-1", "NEW-MR-2"])
		self.assertEqual(submitted, ["NEW-MR-1", "NEW-MR-2"])
		self.assertEqual(result["journal_entries"], ["NEW-MR-1", "NEW-MR-2"])
		self.assertEqual(result["workflow_state"], "Disbursed")
		sync.assert_called_once_with("FR-1")

	def test_existing_draft_is_submitted_not_duplicated(self):
		result, built, submitted, _sync = self._run([_row("MR-1"), _row("MR-2")], drafts={"MR-1": "ACC-JV-9"})
		self.assertEqual(built, ["NEW-MR-2"])
		self.assertEqual(submitted, ["ACC-JV-9", "NEW-MR-2"])
		self.assertEqual(result["journal_entries"], ["ACC-JV-9", "NEW-MR-2"])

	def test_nothing_outstanding_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._run([])

	def test_needs_permission_to_submit_a_journal_entry(self):
		with self.assertRaises(frappe.PermissionError):
			self._run([_row()], can_submit=False)


class TestPayOptions(unittest.TestCase):
	def _options(self, rows, *, state="Approved", drafts=None):
		drafts = drafts or {}
		with (
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(frappe, "get_doc", return_value=_fr(rows, state)),
			patch.object(funding, "company_currency", return_value="KES"),
			patch.object(frappe.db, "get_value", return_value=OPERATIONAL),
			patch.object(funding, "_draft_journal_entry", side_effect=lambda fr, mr, cur=None: drafts.get(mr)),
			patch.object(funding, "_company_bank_or_cash_account", return_value="Bank - C"),
			patch.object(funding, "_pay_option_label", return_value="row"),
		):
			return funding.get_funding_pay_options("FR-1")

	def test_unpaid_row_is_offered_with_its_currency(self):
		options = self._options([_row("MR-1", "USD")])
		self.assertEqual(len(options["operational"]), 1)
		self.assertEqual(options["currencies"], ["USD"])

	def test_row_with_a_draft_is_still_offered_but_needs_no_bank(self):
		options = self._options([_row("MR-1")], drafts={"MR-1": "ACC-JV-9"})
		self.assertEqual(options["operational"][0]["draft_entry"], "ACC-JV-9")
		self.assertEqual(options["currencies"], [])

	def test_paid_row_is_not_offered(self):
		self.assertEqual(self._options([_row(funded=1000)])["operational"], [])

	def test_completed_request_offers_nothing(self):
		"""Even with a row that looks unpaid: Completed is closed."""
		options = self._options([_row()], state="Completed")
		self.assertEqual(options["operational"], [])
		self.assertEqual(options["purchase"], [])

	def test_disbursed_request_with_a_new_unpaid_row_still_offers_it(self):
		self.assertEqual(len(self._options([_row()], state="Disbursed")["operational"]), 1)


class TestClosedRequestRefusesPayment(unittest.TestCase):
	def test_completed_request_cannot_raise_payment_documents(self):
		with self.assertRaises(frappe.ValidationError):
			funding._assert_funding_request_approved(_fr([], "Completed"))

	def test_approved_request_can(self):
		funding._assert_funding_request_approved(_fr([], "Approved"))


class TestFullyPaidDespiteRateMovement(unittest.TestCase):
	"""USD 1,000 approved at 129.60 and paid at 129.58: paid in full, KES 20 apart."""

	def _state(self, **kw):
		wf = frappe._dict(
			progress_states=lambda: {"Approved", "Disbursement in Progress", "Disbursed"},
			disbursed_states=lambda: frozenset({"Disbursed"}),
			disbursement_state="Disbursement in Progress",
			is_disbursed=lambda s: s == "Disbursed",
		)
		with patch.object(funding, "get_funding_workflow_map", return_value=wf):
			return funding.funding_progress_state("Disbursement in Progress", 179580, 179600, **kw)

	def test_totals_alone_leave_it_in_progress(self):
		self.assertEqual(self._state(), "Disbursement in Progress")

	def test_every_row_paid_in_its_own_currency_is_disbursed(self):
		self.assertEqual(self._state(rows_fully_paid=True), "Disbursed")


class TestDisburseIsAWorkflowAction(unittest.TestCase):
	"""Moving into Disbursed by a workflow action is what pays."""

	CTRL = "cgm_shipping.cgm_worldwide_shipping.doctype.funding_request.funding_request"

	def _save(self, before, after):
		from cgm_shipping.cgm_worldwide_shipping.doctype.funding_request.funding_request import FundingRequest

		doc = MagicMock(spec=FundingRequest)
		doc.name = "FR-1"
		doc.workflow_state = after
		doc.get_doc_before_save.return_value = frappe._dict(workflow_state=before) if before else None
		wf = frappe._dict(is_disbursed=lambda s: s == "Disbursed")
		with (
			patch(f"{self.CTRL}.get_funding_workflow_map", return_value=wf),
			patch.object(funding, "disburse_on_workflow_action") as disburse,
		):
			FundingRequest._disburse_on_workflow_action(doc)
		return disburse, doc

	def test_approved_to_disbursed_pays(self):
		disburse, doc = self._save("Approved", "Disbursed")
		disburse.assert_called_once_with("FR-1")
		doc.reload.assert_called_once()

	def test_saving_an_already_disbursed_request_does_not_pay_again(self):
		self._save("Disbursed", "Disbursed")[0].assert_not_called()

	def test_other_transitions_do_not_pay(self):
		self._save("Disbursed", "Completed")[0].assert_not_called()
		self._save("Pending", "Approved")[0].assert_not_called()

	def test_accounts_chosen_on_the_form_reach_the_payment_once(self):
		store = {}
		cache = frappe._dict(
			set_value=lambda k, v, expires_in_sec=None: store.__setitem__(k, v),
			get_value=lambda k: store.get(k),
			delete_value=lambda k: store.pop(k, None),
		)
		with (
			patch.object(frappe, "cache", cache),
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(
				funding, "disburse_funding_request", return_value={"journal_entries": ["JV-1"]}
			) as pay,
		):
			funding.set_disbursement_accounts("FR-1", '{"USD": "Bank USD"}')
			self.assertEqual(funding.disburse_on_workflow_action("FR-1"), ["JV-1"])
			pay.assert_called_once_with("FR-1", {"USD": "Bank USD"})
			self.assertEqual(funding.get_last_disbursement("FR-1"), ["JV-1"])
			self.assertEqual(funding.get_last_disbursement("FR-1"), [], "read once")
			funding.disburse_on_workflow_action("FR-1")
			self.assertEqual(pay.call_args.args, ("FR-1", {}), "accounts are not reused")


class TestEnsureDisburseTransition(unittest.TestCase):
	def _workflow(self, transitions):
		wf = MagicMock()
		wf.name = "WF"
		wf.transitions = [frappe._dict(t) for t in transitions]
		wf.states = [frappe._dict(state=s, allow_edit="Finance User") for s in ("Approved", "Partially Approved", "Disbursement in Progress", "Disbursed", "Completed")]
		wf.append.side_effect = lambda table, row: wf.transitions.append(frappe._dict(row))
		return wf

	def _run(self, transitions):
		from cgm_shipping.cgm_worldwide_shipping.customizations import funding_workflow as fw

		wf = self._workflow(transitions)
		wmap = frappe._dict(
			disbursed_states=lambda: frozenset({"Disbursed"}),
			approve_next_states=frozenset({"Approved"}),
			partial_state="Partially Approved",
			disbursement_state="Disbursement in Progress",
		)
		with (
			patch.object(fw, "load_funding_request_workflow", return_value=wf),
			patch.object(frappe, "get_doc", return_value=wf),
			patch.object(fw, "get_funding_workflow_map", return_value=wmap),
			patch.object(fw, "_ensure_workflow_action_masters"),
			patch.object(frappe, "clear_cache"),
		):
			changed = fw.ensure_funding_disburse_transition()
		return changed, wf

	BASE = [
		{"state": "Approved", "action": "Cancel", "next_state": "Cancelled", "allowed": "Finance User"},
		{"state": "Partially Approved", "action": "Cancel", "next_state": "Cancelled", "allowed": "Finance User"},
		{"state": "Disbursement in Progress", "action": "Cancel", "next_state": "Cancelled", "allowed": "Finance User"},
		{"state": "Disbursed", "action": "Complete", "next_state": "Completed", "allowed": "Finance User"},
	]

	def test_adds_disburse_from_every_payable_state(self):
		changed, wf = self._run(self.BASE)
		self.assertTrue(changed)
		added = [(t.state, t.next_state, t.allowed) for t in wf.transitions if t.action == "Disburse"]
		self.assertEqual(
			added,
			[
				("Approved", "Disbursed", "Finance User"),
				("Partially Approved", "Disbursed", "Finance User"),
				("Disbursement in Progress", "Disbursed", "Finance User"),
			],
		)
		wf.save.assert_called_once()

	def test_running_again_changes_nothing(self):
		_changed, wf = self._run(self.BASE)
		again, wf2 = self._run([dict(t) for t in wf.transitions])
		self.assertFalse(again)
		wf2.save.assert_not_called()

	def test_an_existing_disburse_transition_is_left_as_the_desk_has_it(self):
		custom = {"state": "Approved", "action": "Disburse", "next_state": "Disbursed", "allowed": "Finance Manager"}
		_changed, wf = self._run([*self.BASE, custom])
		approved = [t for t in wf.transitions if t.state == "Approved" and t.action == "Disburse"]
		self.assertEqual(len(approved), 1)
		self.assertEqual(approved[0].allowed, "Finance Manager")


class TestStateMapWithDisburse(unittest.TestCase):
	"""Adding the Disburse transitions must not change what the states mean."""

	def _map(self, with_disburse):
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import FundingWorkflowMap

		states = [
			("Draft", 0), ("Pending", 0), ("Approved", 1), ("Partially Approved", 1),
			("Disbursement in Progress", 1), ("Disbursed", 1), ("Completed", 1), ("Rejected", 0), ("Cancelled", 2),
		]
		transitions = [
			("Draft", "Submit", "Pending"), ("Pending", "Approve", "Approved"), ("Pending", "Reject", "Rejected"),
			("Approved", "Cancel", "Cancelled"), ("Disbursed", "Complete", "Completed"),
		]
		if with_disburse:
			transitions += [(s, "Disburse", "Disbursed") for s in ("Approved", "Partially Approved", "Disbursement in Progress")]
		return FundingWorkflowMap.from_workflow(
			{
				"states": [{"state": s, "doc_status": ds} for s, ds in states],
				"transitions": [{"state": a, "action": act, "next_state": b} for a, act, b in transitions],
			}
		)

	def test_the_map_is_the_same_with_and_without_disburse(self):
		self.assertEqual(self._map(True), self._map(False))

	def test_disbursed_is_not_fully_complete_and_completed_is(self):
		wf = self._map(True)
		self.assertFalse(wf.is_fully_complete("Disbursed"))
		self.assertTrue(wf.is_fully_complete("Completed"))
		self.assertTrue(wf.is_disbursed("Disbursed"))
		self.assertFalse(wf.is_fully_complete("Approved"))
