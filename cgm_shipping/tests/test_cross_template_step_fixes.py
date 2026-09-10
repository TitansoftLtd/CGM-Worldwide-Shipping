"""Checks that read Sea Import step numbers now read the task's stamps.

Several checks took a task's step number and asked what that number means in
Sea Import. On the other templates the same number is a different step, so:
finance steps on Road Transit, Air Import and Sea Transit could not be saved as
Completed (their application never looked "ready"), a Road Transit permit step
got the UCR finance profile, and the "transport runs in parallel" rule still
used the old transport numbers 21-26, which let a Sea Import shipment close
with trucks and container returns still open.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import sea_clearance as sc
from cgm_shipping.cgm_worldwide_shipping.customizations import task_behaviour as tb

ROAD = "Road Transit Inbound Workflow"


def _row(seq, step=""):
	return frappe._dict(seq=seq, container_step=step, name=f"TASK-{seq}")


class TestParallelTransport(unittest.TestCase):
	ROWS = [_row(12), _row(17, "Field Clearance"), _row(20, "Book Trucks"), _row(21, "Gate Out")]

	def test_transport_gate_keeps_its_own_task(self):
		kept = sc._without_parallel_transport(self.ROWS, 21, True)
		self.assertEqual([r.seq for r in kept], [12, 17, 21])

	def test_other_gates_keep_every_open_task(self):
		self.assertEqual(sc._without_parallel_transport(self.ROWS, 19, False), self.ROWS)


class TestClosure(unittest.TestCase):
	def test_closure_checks_every_task_up_to_the_last_step(self):
		template = [{"sequence_no": seq} for seq in range(1, 26) if seq not in (7, 9)]
		with patch.object(sc, "load_sea_task_template", return_value=template), patch.object(
			sc, "task_flow_key_in_filter", return_value=["in", ["Sea Import Workflow"]]
		), patch.object(sc.frappe.db, "exists", return_value=True), patch.object(
			sc.frappe.db, "count", return_value=len(template)
		), patch.object(sc, "get_incomplete_sea_tasks", return_value=[]) as incomplete:
			self.assertEqual(sc.get_sea_closure_blockers("PROJ-TEST"), [])
		incomplete.assert_called_once_with("PROJ-TEST", 26, parallel_transport=False)


class TestApplicationReadyForFinance(unittest.TestCase):
	def _ready(self, task, *, submitted=False, ucr=False, permits=False):
		with patch.object(sc.frappe, "get_doc", return_value=task), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.application_finance.invoice_submitted",
			return_value=submitted,
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.ucr_invoice_ready",
			return_value=ucr,
		), patch(
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow.permit_application_invoices_ready_for_finance",
			return_value=permits,
		):
			return sc.application_ready_for_finance(task.name)

	def _task(self, role, kind="", seq=2):
		return frappe._dict(
			name="TASK-APP",
			custom_task_flow_key=ROAD,
			custom_task_role=role,
			custom_payment_kind=kind,
			custom_sequence_no=seq,
		)

	def test_other_templates_application_is_read_by_its_stamps(self):
		# Road Transit's step 2 is the UCR application; in Sea Import step 2 shares documents.
		self.assertTrue(self._ready(self._task("Application", "UCR"), submitted=True))
		self.assertFalse(self._ready(self._task("Application", "UCR")))

	def test_permit_application_waits_for_its_invoices(self):
		task = self._task("Permit Application", seq=4)
		self.assertTrue(self._ready(task, permits=True))
		self.assertFalse(self._ready(task))

	def test_a_step_that_is_no_application_is_not_ready(self):
		self.assertFalse(self._ready(self._task("Document"), submitted=True, ucr=True, permits=True))


class TestProfileFallback(unittest.TestCase):
	def test_other_templates_task_without_a_kind_has_no_profile(self):
		# Road Transit's permit step 4 used to come out as Sea Import's step 4: UCR finance.
		task = frappe._dict(
			custom_task_flow_key=ROAD,
			custom_task_role="Permit Application",
			custom_payment_kind="",
			custom_sequence_no=4,
		)
		self.assertIsNone(tb.profile_for_behaviour_task(task))


class TestPermitInvoicesCountAsDone(unittest.TestCase):
	def test_permit_application_by_its_role_on_any_template(self):
		rows = [
			{"custom_sequence_no": 13, "status": "Open", "custom_permit_invoices_submitted": 1,
			 "custom_task_role": "Permit Application"},
		]
		self.assertEqual(sc.effective_completed_task_seqs(rows), {13})

	def test_the_role_decides_not_the_step_number(self):
		# Step 5 is Sea Import's pre-clearance permit application, but this row is finance.
		rows = [
			{"custom_sequence_no": 5, "status": "Open", "custom_permit_invoices_submitted": 1,
			 "custom_task_role": "Permit Finance"},
		]
		self.assertEqual(sc.effective_completed_task_seqs(rows), set())
