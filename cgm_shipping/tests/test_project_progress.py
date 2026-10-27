"""A Project's percentage has to agree with its tasks, however the tasks were written.

PROJ-0002 read 100% with a task still open, so ERPNext also read its status as Completed
and a live shipment sat in everyone's "Completed" filter. The cause was a patch reopening
a task with `frappe.db.set_value`, which runs no hooks, so nothing told the project to
recount.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import project_progress as pp


def _run(projects, counts):
	written = {}
	with (
		patch.object(pp, "_task_counts", return_value=counts),
		patch.object(frappe, "get_all", return_value=[frappe._dict(p) for p in projects]),
		patch.object(frappe.db, "set_value",
		             side_effect=lambda dt, name, values, **kw: written.__setitem__(name, values)),
		patch.object(frappe.db, "commit"),
		patch.object(frappe, "log_error"),
	):
		pp.reconcile_project_progress()
	return written


class TestProjectProgressReconciliation(unittest.TestCase):
	def test_a_reopened_task_pulls_the_percentage_back_down(self):
		written = _run([{"name": "PROJ-0002", "status": "Completed", "percent_complete": 100.0}],
		               {"PROJ-0002": (23, 22)})
		self.assertEqual(written["PROJ-0002"], {"percent_complete": 95.65, "status": "Open"})

	def test_a_project_that_already_agrees_is_not_written(self):
		self.assertEqual(
			_run([{"name": "PROJ-0001", "status": "Completed", "percent_complete": 100.0}],
			     {"PROJ-0001": (23, 23)}),
			{},
		)

	def test_a_cancelled_task_counts_as_accounted_for(self):
		# ERPNext counts Cancelled alongside Completed, so this project is finished.
		self.assertEqual(
			_run([{"name": "PROJ-9", "status": "Open", "percent_complete": 100.0}],
			     {"PROJ-9": (10, 10)}),
			{},
		)

	def test_the_percentage_is_corrected_without_touching_an_open_status(self):
		written = _run([{"name": "PROJ-9", "status": "Open", "percent_complete": 100.0}],
		               {"PROJ-9": (10, 5)})
		self.assertEqual(written["PROJ-9"], {"percent_complete": 50.0})

	def test_a_project_with_no_tasks_is_left_alone(self):
		self.assertEqual(
			_run([{"name": "PROJ-9", "status": "Completed", "percent_complete": 100.0}], {}),
			{},
		)
