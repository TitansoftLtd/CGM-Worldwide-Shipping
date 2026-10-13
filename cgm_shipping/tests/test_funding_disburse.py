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
	def _run(self, rows, *, drafts=None, can_submit=True, purchase_rows=(), raised=((), ())):
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
			patch.object(
				funding,
				"_outstanding_rows",
				side_effect=lambda fr, request_type, purchase=False: list(purchase_rows) if purchase else rows,
			),
			patch.object(funding, "_draft_journal_entry", side_effect=lambda fr, mr, cur=None: drafts.get(mr)),
			patch.object(funding, "_build_operational_journal_entry", build),
			patch.object(funding, "_raise_purchase_orders", return_value=(list(raised[0]), list(raised[1]))),
			patch.object(funding, "sync_funding_request_paid_amounts") as sync,
			patch.object(frappe.db, "get_value", return_value="Disbursed"),
		):
			result = funding.disburse_funding_request("FR-1", '{"KES": "Bank - C"}')
		self.last_result = result
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

	def test_purchase_rows_get_a_purchase_order(self):
		"""A request with only purchase rows is not "nothing to disburse"."""
		result, built, submitted, sync = self._run([], purchase_rows=[_row("MR-P")], raised=(["PO-1"], []))
		self.assertEqual((built, submitted), ([], []))
		self.assertEqual(result["purchase_orders"], ["PO-1"])
		self.assertEqual(result["journal_entries"], [])
		sync.assert_called_once_with("FR-1")

	def test_mixed_request_gets_both(self):
		result, _built, submitted, _sync = self._run(
			[_row("MR-1")], purchase_rows=[_row("MR-P")], raised=(["PO-1"], [])
		)
		self.assertEqual(submitted, ["NEW-MR-1"])
		self.assertEqual(result["purchase_orders"], ["PO-1"])

	def test_purchase_only_request_needs_no_journal_entry_permission(self):
		result, _b, _s, _sync = self._run([], purchase_rows=[_row("MR-P")], raised=(["PO-1"], []), can_submit=False)
		self.assertEqual(result["purchase_orders"], ["PO-1"])

	def test_order_already_raised_is_adopted_and_the_request_moves_on(self):
		"""Not a dead end: the order is reported so Finance can continue on it."""
		result, _b, _s, sync = self._run([], purchase_rows=[_row("MR-P")], raised=([], ["PO-9"]))
		self.assertEqual(result["existing_purchase_orders"], ["PO-9"])
		self.assertEqual(result["purchase_orders"], [])
		sync.assert_called_once_with("FR-1")

	def test_existing_order_is_linked_to_the_request_once(self):
		set_value = MagicMock()
		meta = frappe._dict(has_field=lambda f: True)
		with (
			patch.object(frappe, "get_meta", return_value=meta),
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(frappe.db, "set_value", set_value),
		):
			funding._adopt_purchase_order("PO-9", "FR-1")
		self.assertEqual(set_value.call_args.args[:4], ("Purchase Order", "PO-9", "custom_funding_request", "FR-1"))
		set_value.reset_mock()
		with (
			patch.object(frappe, "get_meta", return_value=meta),
			patch.object(frappe.db, "get_value", return_value="FR-OTHER"),
			patch.object(frappe.db, "set_value", set_value),
		):
			funding._adopt_purchase_order("PO-9", "FR-1")
		set_value.assert_not_called()


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
				funding,
				"disburse_funding_request",
				return_value={"journal_entries": ["JV-1"], "purchase_orders": ["PO-1"]},
			) as pay,
		):
			funding.set_disbursement_accounts("FR-1", '{"USD": "Bank USD"}')
			funding.disburse_on_workflow_action("FR-1")
			pay.assert_called_once_with("FR-1", {"USD": "Bank USD"})
			created = {"journal_entries": ["JV-1"], "purchase_orders": ["PO-1"], "existing_purchase_orders": []}
			empty = {"journal_entries": [], "purchase_orders": [], "existing_purchase_orders": []}
			self.assertEqual(funding.get_last_disbursement("FR-1"), created)
			self.assertEqual(funding.get_last_disbursement("FR-1"), empty, "read once")
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

	STEPS = ["Disburse", "Create Purchase Order", "Submit Journal Entry", "Submit Purchase Order", "Record Purchase Payment"]
	PAYABLE = ["Approved", "Partially Approved", "Disbursement in Progress"]

	def test_every_payable_state_gets_one_action_per_pending_step(self):
		changed, wf = self._run(self.BASE)
		self.assertTrue(changed)
		added = {(t.state, t.action): t for t in wf.transitions if t.action in self.STEPS}
		self.assertEqual(len(added), 15)
		for state in self.PAYABLE:
			for step in self.STEPS:
				row = added[(state, step)]
				self.assertEqual(row.condition, f'doc.pending_step == "{step}"')
				self.assertEqual(row.allowed, "Finance User")
		wf.save.assert_called_once()

	def test_paying_steps_lead_to_disbursed_and_order_steps_stay_put(self):
		_changed, wf = self._run(self.BASE)
		for t in wf.transitions:
			if t.action in self.STEPS[:3]:
				self.assertEqual(t.next_state, "Disbursed", t.action)
			elif t.action in self.STEPS[3:]:
				self.assertEqual(t.next_state, t.state, t.action)

	def test_payment_actions_are_listed_before_the_other_actions_of_their_state(self):
		_changed, wf = self._run(self.BASE)
		order = [(t.state, t.action) for t in wf.set.call_args.args[1]]
		expected = []
		for state in self.PAYABLE:
			expected += [(state, step) for step in self.STEPS] + [(state, "Cancel")]
		expected.append(("Disbursed", "Complete"))
		self.assertEqual(order, expected)

	def test_running_again_changes_nothing(self):
		_changed, wf = self._run(self.BASE)
		again, wf2 = self._run([dict(t) for t in wf.transitions])
		self.assertFalse(again)
		wf2.save.assert_not_called()

	def test_an_action_already_there_keeps_its_role_and_gains_its_condition(self):
		custom = {"state": "Approved", "action": "Disburse", "next_state": "Disbursed", "allowed": "Finance Manager"}
		_changed, wf = self._run([*self.BASE, custom])
		approved = [t for t in wf.transitions if t.state == "Approved" and t.action == "Disburse"]
		self.assertEqual(len(approved), 1)
		self.assertEqual(approved[0].allowed, "Finance Manager")
		self.assertEqual(approved[0].condition, 'doc.pending_step == "Disburse"')

	def test_a_condition_written_in_desk_is_kept(self):
		custom = {"state": "Approved", "action": "Disburse", "next_state": "Disbursed", "allowed": "Finance User", "condition": "doc.total_approved > 0"}
		_changed, wf = self._run([*self.BASE, custom])
		row = [t for t in wf.transitions if t.state == "Approved" and t.action == "Disburse"][0]
		self.assertEqual(row.condition, "doc.total_approved > 0")


class TestTidyActions(unittest.TestCase):
	def _run(self, transitions):
		from cgm_shipping.cgm_worldwide_shipping.customizations import funding_workflow as fw

		wf = MagicMock()
		wf.name = "WF"
		wf.transitions = [frappe._dict(t) for t in transitions]
		wf.states = [frappe._dict(state="Approved", doc_status=1), frappe._dict(state="Cancelled", doc_status=2), frappe._dict(state="Disbursed", doc_status=1)]
		wf.set.side_effect = lambda table, rows: setattr(wf, "transitions", list(rows))
		with (
			patch.object(fw, "load_funding_request_workflow", return_value=wf),
			patch.object(frappe, "get_doc", return_value=wf),
			patch.object(fw, "_ensure_workflow_action_masters"),
			patch.object(frappe, "clear_cache"),
		):
			result = fw.tidy_funding_request_actions()
		return result, wf

	ROWS = [
		{"state": "Approved", "action": "Cancel", "next_state": "Cancelled"},
		{"state": "Approved", "action": "Disburse", "next_state": "Disbursed"},
	]

	def test_cancel_is_renamed_and_disburse_moved_up(self):
		result, wf = self._run(self.ROWS)
		self.assertEqual(result, {"renamed": 1, "reordered": True})
		self.assertEqual([t.action for t in wf.transitions], ["Disburse", "Cancel Request"])
		wf.save.assert_called_once()

	def test_second_run_changes_nothing(self):
		_result, wf = self._run(self.ROWS)
		again, wf2 = self._run([dict(t) for t in wf.transitions])
		self.assertEqual(again, {"renamed": 0, "reordered": False})
		wf2.save.assert_not_called()

	def test_a_name_chosen_in_desk_is_kept(self):
		rows = [{"state": "Approved", "action": "Withdraw", "next_state": "Cancelled"}]
		result, wf = self._run(rows)
		self.assertEqual(result["renamed"], 0)
		self.assertEqual(wf.transitions[0].action, "Withdraw")

	def test_only_the_action_that_cancels_is_renamed(self):
		rows = [{"state": "Approved", "action": "Cancel", "next_state": "Disbursed"}]
		self.assertEqual(self._run(rows)[0]["renamed"], 0)


class TestPendingStep(unittest.TestCase):
	"""The action is named after what the request is waiting on, row by row."""

	def _step(self, rows, *, types, drafts=None, orders=None, state="Approved"):
		drafts, orders = drafts or {}, orders or {}

		def get_value(doctype, name, field, *a, **k):
			if doctype == "Material Request":
				return types[name]
			if doctype == "Purchase Order":
				return orders[name]
			return None

		wf = frappe._dict(is_fully_complete=lambda s: s == "Completed")
		with (
			patch.object(funding, "funding_is_approved", return_value=state != "Pending"),
			patch.object(funding, "get_funding_workflow_map", return_value=wf),
			patch.object(frappe.db, "get_value", get_value),
			patch.object(funding, "_draft_journal_entry", side_effect=lambda fr, mr, cur=None: drafts.get(mr)),
			patch.object(funding, "_open_purchase_order_name", side_effect=lambda mr: next((po for po in orders if po.endswith(mr)), None)),
		):
			return funding.funding_pending_step(_fr(rows, state))

	OP, PU = funding.MATERIAL_REQUEST_TYPE_OPERATIONAL, "Purchase"

	def test_unpaid_expense_row_is_disburse(self):
		self.assertEqual(self._step([_row("A")], types={"A": self.OP}), "Disburse")

	def test_purchase_row_with_no_order_is_create_purchase_order(self):
		self.assertEqual(self._step([_row("A")], types={"A": self.PU}), "Create Purchase Order")

	def test_draft_journal_entry_is_submit_journal_entry(self):
		self.assertEqual(self._step([_row("A")], types={"A": self.OP}, drafts={"A": "JV-1"}), "Submit Journal Entry")

	def test_draft_order_is_submit_purchase_order(self):
		self.assertEqual(self._step([_row("A")], types={"A": self.PU}, orders={"PO-A": 0}), "Submit Purchase Order")

	def test_submitted_unpaid_order_is_record_purchase_payment(self):
		self.assertEqual(self._step([_row("A")], types={"A": self.PU}, orders={"PO-A": 1}), "Record Purchase Payment")

	def test_earliest_unfinished_step_wins(self):
		rows = [_row("A"), _row("B")]
		self.assertEqual(self._step(rows, types={"A": self.OP, "B": self.PU}, orders={"PO-B": 1}), "Disburse")
		self.assertEqual(
			self._step(rows, types={"A": self.OP, "B": self.PU}, drafts={"A": "JV-1"}, orders={"PO-B": 1}),
			"Submit Journal Entry",
		)

	def test_nothing_pending_when_paid_unapproved_or_closed(self):
		self.assertEqual(self._step([_row("A", funded=1000)], types={"A": self.OP}), "")
		self.assertEqual(self._step([_row("A")], types={"A": self.OP}, state="Pending"), "")
		self.assertEqual(self._step([_row("A")], types={"A": self.OP}, state="Completed"), "")



class TestCancelTakesPaymentDocuments(unittest.TestCase):
	"""Cancelling a request deletes its drafts and cancels what was submitted."""

	def _run(self, documents, *, may_cancel=True):
		deleted, cancelled, unlinked = [], [], []

		def get_doc(doctype, name):
			doc = MagicMock()
			doc.doctype, doc.name = doctype, name
			doc.cancel.side_effect = lambda: cancelled.append(name)
			return doc

		def has_permission(doctype, ptype, doc=None, throw=False):
			if not may_cancel:
				raise frappe.PermissionError
			return True

		with (
			patch.object(funding, "funding_payment_documents", return_value=documents),
			patch.object(frappe, "has_permission", has_permission),
			patch.object(frappe, "delete_doc", side_effect=lambda dt, n, **k: deleted.append(n)),
			patch.object(frappe, "get_doc", get_doc),
			patch.object(funding, "_unlink_from_material_request", side_effect=lambda d: unlinked.append(d.name)),
		):
			result = funding.cancel_funding_payment_documents(frappe._dict(name="FR-1"))
			flag_after = frappe.flags.get("cgm_funding_cancelling")
		return result, deleted, cancelled, unlinked, flag_after

	DOCS = [
		{"doctype": "Journal Entry", "name": "JV-DRAFT", "docstatus": 0},
		{"doctype": "Journal Entry", "name": "JV-POSTED", "docstatus": 1},
		{"doctype": "Purchase Order", "name": "PO-DRAFT", "docstatus": 0},
		{"doctype": "Purchase Order", "name": "PO-PLACED", "docstatus": 1},
	]

	def test_drafts_are_deleted_and_submitted_are_cancelled(self):
		result, deleted, cancelled, unlinked, flag = self._run(self.DOCS)
		self.assertEqual(deleted, ["JV-DRAFT", "PO-DRAFT"])
		self.assertEqual(cancelled, ["JV-POSTED", "PO-PLACED"])
		self.assertEqual(result, {"deleted": ["JV-DRAFT", "PO-DRAFT"], "cancelled": ["JV-POSTED", "PO-PLACED"]})
		self.assertIsNone(flag, "the cancelling flag must not outlive the cancel")

	def test_cancelled_documents_are_unlinked_from_the_material_request(self):
		_result, _deleted, _cancelled, unlinked, _flag = self._run(self.DOCS)
		self.assertEqual(unlinked, ["JV-POSTED", "PO-PLACED"])

	def test_nothing_is_touched_without_permission_to_cancel_the_submitted_ones(self):
		with self.assertRaises(frappe.PermissionError):
			self._run(self.DOCS, may_cancel=False)

	def test_a_request_with_no_documents_cancels_cleanly(self):
		self.assertEqual(self._run([])[0], {"deleted": [], "cancelled": []})

	def test_sync_stands_down_for_the_request_being_cancelled(self):
		frappe.flags.cgm_funding_cancelling = "FR-1"
		try:
			with (
				patch.object(frappe.db, "exists", return_value=True),
				patch.object(frappe, "get_doc") as get_doc,
			):
				funding.sync_funding_request_paid_amounts("FR-1")
			get_doc.assert_not_called()
		finally:
			frappe.flags.cgm_funding_cancelling = None


class TestMaterialRequestMirrorsItsRow(unittest.TestCase):
	STATES = frozenset({"Approved", "Disbursement in Progress", "Disbursed", "Rejected"})

	def _state(self, fr_state, approved, funded, *, started=False, mr_states=None):
		wf = frappe._dict(disbursement_state="Disbursement in Progress")
		with (
			patch.object(funding, "mr_workflow_state_from_funding_request", return_value=fr_state),
			patch.object(funding, "get_funding_workflow_map", return_value=wf),
		):
			return funding.mr_row_workflow_state(
				fr_state, approved, funded, mr_workflow=mr_states or self.STATES, payment_started=started
			)

	def test_paid_row_is_disbursed_even_while_the_batch_is_in_progress(self):
		self.assertEqual(self._state("Disbursement in Progress", 1000, 1000), "Disbursed")

	def test_row_with_its_document_raised_is_in_progress(self):
		self.assertEqual(self._state("Disbursement in Progress", 1000, 0, started=True), "Disbursement in Progress")
		self.assertEqual(self._state("Approved", 1000, 0, started=True), "Disbursement in Progress")

	def test_row_with_nothing_raised_stays_approved(self):
		self.assertEqual(self._state("Disbursement in Progress", 1000, 0), "Approved")

	def test_without_the_state_on_the_material_request_workflow_it_stays_approved(self):
		old = frozenset({"Approved", "Disbursed"})
		self.assertEqual(self._state("Approved", 1000, 0, started=True, mr_states=old), "Approved")

	def test_other_states_pass_through(self):
		self.assertEqual(self._state("Rejected", 1000, 0, started=True), "Rejected")


class TestPurchaseOrderPayments(unittest.TestCase):
	def _paid(self, against_invoices, against_orders):
		answers = iter([[[against_invoices]], [[against_orders]]])
		with (
			patch.object(frappe, "get_all", return_value=["PO-1"]),
			patch.object(frappe.db, "sql", side_effect=lambda *a, **k: next(answers)),
		):
			return funding._paid_against_purchase_orders("MR-1")

	def test_an_advance_paid_against_the_order_counts(self):
		"""FR-2026-00005: KES 1,250 paid against the order, no invoice yet, read as unpaid."""
		self.assertEqual(self._paid(0, 1250), 1250)

	def test_invoice_payments_still_count(self):
		self.assertEqual(self._paid(1250, 0), 1250)

	def test_part_advance_and_part_on_invoice_add_up(self):
		self.assertEqual(self._paid(750, 500), 1250)

	def test_a_payment_against_the_order_refreshes_its_request(self):
		doc = frappe._dict(references=[frappe._dict(reference_doctype="Purchase Order", reference_name="PO-1")])
		doc.get = lambda key: doc[key] if key in doc else None
		with (
			patch.object(funding, "_funding_request_from_purchase_order", return_value="FR-1") as find,
			patch.object(funding, "sync_funding_request_paid_amounts") as sync,
		):
			funding.sync_funding_requests_touched_by_payment_entry(doc)
		find.assert_called_once_with("PO-1")
		sync.assert_called_once_with("FR-1")


class TestDisbursedIsTheLastState(unittest.TestCase):
	"""With the Complete step gone, the map must still know what Disbursed is."""

	STATES = [
		("Draft", 0), ("Pending", 0), ("Approved", 1), ("Partially Approved", 1),
		("Disbursement in Progress", 1), ("Disbursed", 1), ("Rejected", 0), ("Cancelled", 2),
	]
	PAYABLE = ("Approved", "Partially Approved", "Disbursement in Progress")

	def _map(self, *, with_paying_actions=True):
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import FundingWorkflowMap

		transitions = [
			("Draft", "Submit", "Pending"), ("Pending", "Approve", "Approved"), ("Pending", "Reject", "Rejected"),
			("Approved", "Cancel Request", "Cancelled"), ("Disbursed", "Cancel Request", "Cancelled"),
		]
		if with_paying_actions:
			transitions += [(s, "Disburse", "Disbursed") for s in self.PAYABLE]
			transitions += [(s, "Submit Purchase Order", s) for s in self.PAYABLE]
		return FundingWorkflowMap.from_workflow(
			{
				"states": [{"state": s, "doc_status": ds} for s, ds in self.STATES],
				"transitions": [{"state": a, "action": act, "next_state": b} for a, act, b in transitions],
			}
		)

	def test_disbursed_is_recognised_without_a_complete_step(self):
		wf = self._map()
		self.assertTrue(wf.is_disbursed("Disbursed"))
		self.assertEqual(wf.disbursed_states(), frozenset({"Disbursed"}))

	def test_recognised_by_name_even_before_the_paying_actions_are_added(self):
		self.assertTrue(self._map(with_paying_actions=False).is_disbursed("Disbursed"))

	def test_the_other_states_keep_their_meaning(self):
		wf = self._map()
		self.assertEqual(wf.partial_state, "Partially Approved")
		self.assertEqual(wf.disbursement_state, "Disbursement in Progress")
		self.assertEqual(wf.approve_next_states, frozenset({"Approved"}))
		self.assertEqual(wf.cancel_state, "Cancelled")
		self.assertFalse(wf.is_fully_complete("Disbursed"))
		self.assertFalse(wf.is_terminal("Disbursed"))

	def test_a_disbursed_request_can_still_fall_back_when_its_payment_is_undone(self):
		"""Cancelling the entry that paid it must take it out of Disbursed."""
		wf = self._map()
		self.assertIn("Disbursed", wf.progress_states())
		with patch.object(funding, "get_funding_workflow_map", return_value=wf):
			self.assertEqual(funding.funding_progress_state("Disbursed", 0, 1000), "Disbursement in Progress")
			self.assertEqual(funding.funding_progress_state("Disbursement in Progress", 1000, 1000), "Disbursed")

	def test_material_requests_on_a_disbursed_request_read_disbursed(self):
		wf = self._map()
		with patch.object(funding, "get_funding_workflow_map", return_value=wf):
			state = funding.mr_workflow_state_from_funding_request(
				"Disbursed", mr_workflow=frozenset({"Approved", "Disbursed"})
			)
		self.assertEqual(state, "Disbursed")



class TestFoundByTheScenarioRun(unittest.TestCase):
	"""Each of these was a real failure when the flows were run end to end."""

	WF = frappe._dict(
		progress_states=lambda: {"Approved", "Partially Approved", "Disbursement in Progress", "Disbursed"},
		disbursed_states=lambda: frozenset({"Disbursed"}),
		disbursement_state="Disbursement in Progress",
		is_disbursed=lambda s: s == "Disbursed",
	)

	def _state(self, current, funded, **kw):
		with patch.object(funding, "get_funding_workflow_map", return_value=self.WF):
			return funding.funding_progress_state(current, funded, 1000, **kw)

	def test_payment_undone_goes_back_to_approved_not_in_progress(self):
		"""An entry cancelled by hand left the request "in progress" with nothing raised."""
		self.assertEqual(self._state("Disbursed", 0, approved_state="Approved"), "Approved")

	def test_draft_deleted_goes_back_to_approved(self):
		self.assertEqual(self._state("Disbursement in Progress", 0, approved_state="Approved"), "Approved")

	def test_partially_approved_request_goes_back_to_partially_approved(self):
		self.assertEqual(self._state("Disbursed", 0, approved_state="Partially Approved"), "Partially Approved")

	def test_still_in_progress_while_a_document_is_raised(self):
		self.assertEqual(
			self._state("Disbursed", 0, approved_state="Approved", disbursement_started=True),
			"Disbursement in Progress",
		)

	def test_a_paid_order_stops_the_cancel_before_anything_is_touched(self):
		"""ERPNext cancels a paid order and strands the payment; the request must refuse."""
		docs = [
			{"doctype": "Journal Entry", "name": "JV-DRAFT", "docstatus": 0},
			{"doctype": "Purchase Order", "name": "PO-PAID", "docstatus": 1},
		]
		with (
			patch.object(funding, "funding_payment_documents", return_value=docs),
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(funding, "_payments_against_purchase_order", return_value=["ACC-PAY-1"]),
			patch.object(frappe, "delete_doc") as delete_doc,
			patch.object(frappe, "get_doc") as get_doc,
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				funding.cancel_funding_payment_documents(frappe._dict(name="FR-1"))
		self.assertIn("ACC-PAY-1", str(ctx.exception))
		delete_doc.assert_not_called()
		get_doc.assert_not_called()

	def test_orders_raised_before_the_request_are_adopted(self):
		rows = [_row("MR-1"), _row("MR-2")]
		with (
			patch.object(funding, "_outstanding_rows", return_value=rows),
			patch.object(funding, "_open_purchase_order_name", side_effect=lambda mr: {"MR-1": "PO-1"}.get(mr)),
			patch.object(funding, "_adopt_purchase_order") as adopt,
		):
			adopted = funding.adopt_open_purchase_orders(frappe._dict(name="FR-1"))
		self.assertEqual(adopted, ["PO-1"])
		adopt.assert_called_once_with("PO-1", "FR-1")
