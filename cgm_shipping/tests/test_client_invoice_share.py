"""Sharing an invoice with the client follows the per-row client-pays tick.

The Share button appears when the task-level flag is set *or* any invoice row is
marked client-paid (form_has_client_paid_invoice_line in task.js), but the server
used to demand the task-level flag alone. The button offered an action the server
then refused, on 8 production tasks (TASK-2026-00038 and others), and the advice
it gave - tick "Client will pay" on the task - would have declared a whole task
client-paid when the company had already settled part of it.

The second half matters just as much: a mixed task carries invoices the company
paid, and those are not the client's to receive.
"""

import unittest

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import client_invoice_share as cis
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	TASK_FINANCE_FIELD,
	TASK_PERMITS_FIELD,
)

COMPANY_PAID = {"line_type": "Invoice", "attachment": "/co.pdf", "verified": 1, "client_paid_directly": 0}
CLIENT_PAID = {"line_type": "Invoice", "attachment": "/cl.pdf", "verified": 1, "client_paid_directly": 1}


class _Task(frappe._dict):
	def __init__(self, client_paid=0, lines=(), permits=()):
		super().__init__()
		self.name = "TASK-TEST"
		self.custom_client_paid_directly = client_paid
		self[TASK_FINANCE_FIELD] = [
			frappe._dict(row, name=f"line{i}") for i, row in enumerate(lines)
		]
		self[TASK_PERMITS_FIELD] = [
			frappe._dict(row, name=f"permit{i}") for i, row in enumerate(permits)
		]
		self.meta = frappe._dict(has_field=lambda f: True)


class TestShareGuard(unittest.TestCase):
	"""Who may share: the task-level flag, or any one row marked client-paid."""

	def test_nothing_client_paid_is_refused(self):
		self.assertFalse(cis.task_has_client_paid_work(_Task(lines=[COMPANY_PAID])))

	def test_task_level_flag_allows(self):
		self.assertTrue(cis.task_has_client_paid_work(_Task(client_paid=1)))

	def test_one_client_paid_line_allows(self):
		"""The mismatch that refused an action the button had already offered."""
		self.assertTrue(cis.task_has_client_paid_work(_Task(lines=[COMPANY_PAID, CLIENT_PAID])))

	def test_client_paid_permit_row_allows(self):
		self.assertTrue(
			cis.task_has_client_paid_work(_Task(permits=[{"client_reported_paid": 1}]))
		)


class TestWhatGetsShared(unittest.TestCase):
	"""A mixed task shares the client's invoices, not the company's."""

	def setUp(self):
		if not frappe.get_meta("Task Finance Line").has_field("shared_with_client"):
			self.skipTest("Task Finance Line has no shared_with_client field on this site.")

	def _shared(self, task):
		return set(cis._shareable_finance_line_names(task))

	def test_mixed_task_shares_only_the_client_paid_line(self):
		task = _Task(lines=[COMPANY_PAID, CLIENT_PAID])
		self.assertEqual(self._shared(task), {"line1"})

	def test_task_level_flag_shares_every_verified_invoice(self):
		task = _Task(client_paid=1, lines=[COMPANY_PAID, CLIENT_PAID])
		self.assertEqual(self._shared(task), {"line0", "line1"})

	def test_already_shared_row_is_not_shared_again(self):
		task = _Task(client_paid=1, lines=[dict(CLIENT_PAID, shared_with_client=1)])
		self.assertEqual(self._shared(task), set())

	def test_unverified_invoice_is_not_shared(self):
		task = _Task(client_paid=1, lines=[dict(CLIENT_PAID, verified=0)])
		self.assertEqual(self._shared(task), set())
