"""Permit application <-> Finance closure, verification, and the shared "row paid" rule.

Rules pinned here:

* The declarant cannot complete a permit application (pre- or post-clearance)
  until every invoice and every receipt on the paired Finance task is verified.
* Once they have, Finance closes on payment alone - verification is not
  re-checked, and the reopen rule stops reopening for it. A new unpaid
  amendment row still reopens.
* Three checks used to disagree on whether a row was paid, so a Finance task
  flipped between Completed and Open. They now share one rule.
* Finance can find its application again: it filtered on a Payment Kind that
  application tasks never carry, so the lookup failed for every task.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import workflow as wf

BEHAVIOUR = "cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour"


def _row(**fields):
	return frappe._dict(fields)


def _je_docstatus(docstatus):
	"""Patch the Journal / Payment Entry docstatus lookup."""
	return patch.object(frappe.db, "get_value", return_value=docstatus)


class TestRowPaid(unittest.TestCase):
	def test_task_level_client_paid_counts(self):
		self.assertTrue(wf.permit_finance_row_paid(_row(), client_paid=True))

	def test_draft_journal_entry_counts(self):
		with _je_docstatus(0):
			self.assertTrue(wf.permit_finance_row_paid(_row(journal_entry="ACC-JV-1")))

	def test_cancelled_journal_entry_does_not(self):
		with _je_docstatus(2):
			self.assertFalse(wf.permit_finance_row_paid(_row(journal_entry="ACC-JV-1")))

	def test_missing_journal_entry_does_not(self):
		with _je_docstatus(None):
			self.assertFalse(wf.permit_finance_row_paid(_row(journal_entry="ACC-JV-GONE")))

	def test_row_level_client_paid_counts(self):
		self.assertTrue(wf.permit_finance_row_paid(_row(client_reported_paid=1)))

	def test_unpaid_row(self):
		self.assertFalse(wf.permit_finance_row_paid(_row()))

	def test_settled_needs_verification(self):
		with _je_docstatus(0):
			self.assertFalse(
				wf.permit_finance_row_settled(_row(journal_entry="ACC-JV-1", invoice_verified=0))
			)
			self.assertTrue(
				wf.permit_finance_row_settled(_row(journal_entry="ACC-JV-1", invoice_verified=1))
			)


class TestGateAgreesWithReopen(unittest.TestCase):
	"""Heal must never complete a task the reopen rule would reopen."""

	def _gate(self, rows):
		task = frappe._dict(status="Open")
		with (
			patch.object(wf, "is_permit_finance_task_doc", return_value=True),
			patch.object(wf, "permit_finance_rows", return_value=rows),
			patch.object(wf, "task_client_paid_directly", return_value=False),
			patch.object(wf, "submitted_journal_entry", return_value=True),
		):
			return wf.can_complete_finance_permit_task(task)

	def _pending(self, rows):
		with (
			patch.object(wf, "permit_finance_rows", return_value=rows),
			patch.object(wf, "task_client_paid_directly", return_value=False),
			patch.object(wf, "_permit_application_completed", return_value=False),
			_je_docstatus(1),
		):
			return wf.permit_finance_rows_needing_work(frappe._dict())

	def test_posted_but_unverified_is_not_ready(self):
		"""Used to heal to Completed, then be reopened - the Completed/Open flip."""
		rows = [_row(payment_invoice="/f.pdf", journal_entry="ACC-JV-1", invoice_verified=0)]
		self.assertFalse(self._gate(rows))
		self.assertTrue(self._pending(rows))

	def test_posted_and_verified_is_ready_and_not_pending(self):
		rows = [_row(payment_invoice="/f.pdf", journal_entry="ACC-JV-1", invoice_verified=1)]
		self.assertTrue(self._gate(rows))
		self.assertFalse(self._pending(rows))


class TestReopenAfterDeclarantCompleted(unittest.TestCase):
	"""After the declarant completes, only payment is re-checked."""

	def _pending(self, rows, *, application_completed):
		with (
			patch.object(wf, "permit_finance_rows", return_value=rows),
			patch.object(wf, "task_client_paid_directly", return_value=False),
			patch.object(wf, "_permit_application_completed", return_value=application_completed),
			_je_docstatus(0),
		):
			return wf.permit_finance_rows_needing_work(frappe._dict())

	def test_missing_tick_no_longer_reopens(self):
		rows = [_row(payment_invoice="/f.pdf", journal_entry="ACC-JV-1", invoice_verified=0)]
		self.assertFalse(self._pending(rows, application_completed=True))
		self.assertTrue(self._pending(rows, application_completed=False))

	def test_new_unpaid_amendment_still_reopens(self):
		rows = [_row(payment_invoice="/amendment.pdf", invoice_verified=0)]
		self.assertTrue(self._pending(rows, application_completed=True))


class TestVerificationGate(unittest.TestCase):
	"""The declarant cannot complete until every invoice and receipt is verified."""

	def _check(self, rows, *, finance="FIN"):
		app = frappe._dict(name="APP", project="PROJ", custom_sequence_no=5)
		with (
			patch(f"{BEHAVIOUR}.get_permit_finance_for_behaviour", return_value=finance),
			patch.object(frappe, "get_doc", return_value=frappe._dict(name=finance)),
			patch.object(wf, "permit_finance_rows", return_value=rows),
			patch.object(frappe.db, "get_value", return_value="Finance pays Pre-Clearance Permits"),
		):
			wf.validate_permit_rows_verified(app)

	def test_unverified_invoice_blocks(self):
		rows = [_row(permit_type="DVS", invoice_verified=0, receipt_verified=1)]
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._check(rows)
		self.assertIn("DVS", str(ctx.exception))

	def test_unverified_receipt_blocks(self):
		rows = [_row(permit_type="NBA", invoice_verified=1, receipt_verified=0)]
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._check(rows)
		self.assertIn("NBA", str(ctx.exception))

	def test_everything_verified_passes(self):
		self._check([_row(permit_type="DVS", invoice_verified=1, receipt_verified=1)])

	def test_nothing_to_pay_passes(self):
		self._check([])

	def test_no_finance_task_passes(self):
		self._check([_row(permit_type="DVS")], finance=None)


class TestAutoCloseRespectsVerification(unittest.TestCase):
	"""Finance finishing must not auto-close an application with unverified rows.

	That path runs under the flag that short-circuits the application gate, so
	verification is checked explicitly there.
	"""

	def _close(self, pending):
		fin = frappe._dict(name="FIN", status="Completed", completed_by=None, completed_on=None)
		set_value = MagicMock()
		with (
			patch.object(wf, "is_permit_finance_task_doc", return_value=True),
			patch.object(wf, "task_client_paid_directly", return_value=False),
			patch.object(wf, "get_permit_application_task_for_finance", return_value="APP"),
			patch.object(frappe.db, "get_value", return_value="Open"),
			patch.object(frappe, "get_doc", return_value=frappe._dict(name="APP")),
			patch.object(wf, "merge_project_permits_into_application_task"),
			patch.object(wf, "validate_permit_application_can_complete"),
			patch.object(wf, "permit_rows_pending_verification", return_value=pending),
			patch.object(frappe.db, "set_value", set_value),
			patch.object(frappe, "clear_document_cache"),
		):
			wf.close_permit_application_when_finance_done(fin)
		return set_value

	def test_unverified_receipt_keeps_application_open(self):
		self._close(([], ["DVS"], "FIN")).assert_not_called()

	def test_all_verified_closes_application(self):
		self._close(([], [], "FIN")).assert_called_once()


class TestApplicationClosesFinance(unittest.TestCase):
	def setUp(self):
		self.app = frappe._dict(
			name="APP", status="Completed", project="PROJ", completed_by="dec@x", completed_on=None
		)
		self.fin = frappe._dict(name="FIN", status="Open", completed_by=None, completed_on=None)
		self.hooks = MagicMock()

	def _run(self, rows, *, is_application=True):
		with (
			patch.object(wf, "is_permit_application_task_doc", return_value=is_application),
			patch(f"{BEHAVIOUR}.get_permit_finance_for_behaviour", return_value="FIN"),
			patch.object(frappe, "get_doc", return_value=self.fin),
			patch.object(wf, "permit_finance_rows", return_value=rows),
			patch.object(wf, "task_client_paid_directly", return_value=False),
			patch.object(wf, "run_finance_permit_completion_hooks", self.hooks),
			_je_docstatus(0),
		):
			return wf.complete_permit_finance_when_application_done(self.app)

	def test_paid_finance_is_closed(self):
		result = self._run([_row(journal_entry="ACC-JV-1", invoice_verified=1)])
		self.assertEqual(result, "FIN")
		self.hooks.assert_called_once_with(self.fin)
		self.assertEqual(self.fin.completed_by, "dec@x")

	def test_paid_but_unverified_finance_is_closed(self):
		"""Verification is the declarant's gate's job, not re-checked here."""
		self.assertEqual(self._run([_row(journal_entry="ACC-JV-1", invoice_verified=0)]), "FIN")
		self.hooks.assert_called_once()

	def test_finance_with_nothing_to_pay_is_closed(self):
		"""All-foreign permit steps never completed before."""
		self.assertEqual(self._run([]), "FIN")
		self.hooks.assert_called_once()

	def test_unpaid_row_keeps_finance_open(self):
		self.assertIsNone(self._run([_row(invoice_verified=1)]))
		self.hooks.assert_not_called()

	def test_already_completed_finance_is_left_alone(self):
		self.fin.status = "Completed"
		self.assertIsNone(self._run([]))
		self.hooks.assert_not_called()

	def test_only_on_completed_permit_applications(self):
		self.app.status = "Open"
		self.assertIsNone(self._run([]))
		self.app.status = "Completed"
		self.assertIsNone(self._run([], is_application=False))
		self.hooks.assert_not_called()

	def test_caller_flags_are_restored(self):
		"""Runs inside the application's own save, which may hold these flags."""
		frappe.flags.cgm_auto_completing_sea_task = True
		try:
			self._run([])
			self.assertTrue(frappe.flags.cgm_auto_completing_sea_task)
		finally:
			frappe.flags.cgm_auto_completing_sea_task = False


class TestFinanceFindsItsApplication(unittest.TestCase):
	"""Finance -> application pairing, against real tasks on the site."""

	def test_every_finance_task_finds_its_application(self):
		finance_tasks = frappe.get_all(
			"Task",
			filters={"custom_task_role": "Permit Finance"},
			fields=["name", "project", "custom_permit_stage"],
			limit=25,
		)
		if not finance_tasks:
			self.skipTest("no permit finance tasks on this site")
		for fin in finance_tasks:
			with self.subTest(finance=fin.name):
				app = wf.get_permit_application_task_for_finance(frappe.get_doc("Task", fin.name))
				self.assertTrue(app, "no application found")
				role, project, stage = frappe.db.get_value(
					"Task", app, ["custom_task_role", "project", "custom_permit_stage"]
				)
				self.assertEqual(role, "Permit Application")
				self.assertEqual(project, fin.project)
				self.assertEqual(stage, fin.custom_permit_stage)
