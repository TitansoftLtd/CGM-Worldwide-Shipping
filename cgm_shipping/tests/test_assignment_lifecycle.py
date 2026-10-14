"""Assignments follow the work, in both directions.

A ToDo records who is responsible. Notification routing reads it to decide who to
tell, so a stale assignment does not merely look untidy: it messages someone who
has finished and withholds the message from whoever actually owns the work now.

What was already handled, and what was not:

* Task completion closed its assignments, in two places (ERPNext's
  `Task.unassign_todo` and CGM's own `CGMTask`).
* Task **reopening** did nothing, so work sent back looked unassigned.
* Project completion did nothing at all - neither ERPNext nor CGM closed a
  shipment's assignments - so a finished shipment would have kept its assignees
  for good. Nothing had surfaced only because no shipment on this site has
  reached a finished status yet.
"""

import unittest

import frappe
from frappe.desk.form.assign_to import add as assign_add
from frappe.desk.form.assign_to import set_status

from cgm_shipping.cgm_worldwide_shipping.customizations import assignment_lifecycle as AL


def _statuses(doctype, name):
	return sorted(
		frappe.get_all(
			"ToDo",
			filters={"reference_type": doctype, "reference_name": name},
			pluck="status",
		)
	)


class _Stub(frappe._dict):
	"""A document just complete enough for the hooks."""

	def __init__(self, before=None, **values):
		super().__init__(**values)
		self._before = before
		self.meta = frappe._dict(has_field=lambda f: f in values)

	def is_new(self):
		return self._before is None

	def get_doc_before_save(self):
		return self._before


class TestTaskTransitions(unittest.TestCase):
	"""Which way the status moved decides what happens."""

	def _run(self, previous, current):
		doc = _Stub(
			before=frappe._dict(status=previous),
			doctype="Task",
			name="TASK-X",
			status=current,
		)
		seen = []
		original = AL.reopen_assignments
		AL.reopen_assignments = lambda dt, n: seen.append((dt, n))
		try:
			AL.on_task_update(doc)
		finally:
			AL.reopen_assignments = original
		return seen

	def test_coming_back_from_completed_reopens(self):
		self.assertEqual(self._run("Completed", "Open"), [("Task", "TASK-X")])

	def test_coming_back_from_cancelled_reopens(self):
		self.assertEqual(self._run("Cancelled", "Working"), [("Task", "TASK-X")])

	def test_being_completed_does_not_reopen(self):
		"""Closing is ERPNext's and CGMTask's job; doing it again here would hide
		where it happens."""
		self.assertEqual(self._run("Open", "Completed"), [])

	def test_an_unchanged_status_does_nothing(self):
		self.assertEqual(self._run("Open", "Open"), [])

	def test_a_new_document_does_nothing(self):
		doc = _Stub(doctype="Task", name="TASK-X", status="Open")
		self.assertEqual(AL.on_task_update(doc), None)


class TestProjectTransitions(unittest.TestCase):
	FIELD = "custom_shipment_status"

	def _run(self, previous, current):
		doc = _Stub(
			before=frappe._dict({self.FIELD: previous}),
			doctype="Project",
			name="PROJ-X",
			**{self.FIELD: current},
		)
		calls = []
		closed, reopened = AL.close_assignments, AL.reopen_assignments
		AL.close_assignments = lambda dt, n: calls.append("close")
		AL.reopen_assignments = lambda dt, n: calls.append("reopen")
		try:
			AL.on_project_update(doc)
		finally:
			AL.close_assignments, AL.reopen_assignments = closed, reopened
		return calls

	def test_finishing_a_shipment_closes(self):
		self.assertEqual(self._run("In Delivery", "Completed"), ["close"])

	def test_settled_counts_as_finished(self):
		self.assertEqual(self._run("In Delivery", "Settled"), ["close"])

	def test_reopening_a_finished_shipment_reopens(self):
		self.assertEqual(self._run("Completed", "In Delivery"), ["reopen"])

	def test_moving_between_two_finished_statuses_does_nothing(self):
		"""Completed to Settled is still finished; nothing should move."""
		self.assertEqual(self._run("Completed", "Settled"), [])

	def test_moving_between_two_live_statuses_does_nothing(self):
		self.assertEqual(self._run("Pre-clearance", "In Delivery"), [])


class TestAgainstRealDocuments(unittest.TestCase):
	"""The hooks, the ToDos and the status field, end to end."""

	USER = "Administrator"

	def setUp(self):
		self.task = frappe.new_doc("Task")
		self.task.subject = "Assignment lifecycle test"
		self.task.status = "Open"
		self.task.flags.ignore_validate = True
		self.task.insert(ignore_permissions=True, ignore_mandatory=True)

	def tearDown(self):
		frappe.db.rollback()

	def _assign(self):
		assign_add(
			{
				"doctype": "Task",
				"name": self.task.name,
				"assign_to": [self.USER],
				"description": "lifecycle test",
			}
		)

	def _set_status(self, status):
		self.task.reload()
		self.task.status = status
		self.task.flags.ignore_validate = True
		self.task.save()

	def test_complete_then_reopen_round_trips(self):
		self._assign()
		self.assertEqual(_statuses("Task", self.task.name), ["Open"])
		self._set_status("Completed")
		self.assertEqual(_statuses("Task", self.task.name), ["Closed"])
		self._set_status("Open")
		self.assertEqual(_statuses("Task", self.task.name), ["Open"])

	def test_a_cancelled_assignment_is_never_revived(self):
		"""Cancelled records somebody being taken off the job. Reopening the work
		does not undo that decision."""
		self._assign()
		self._set_status("Completed")
		todo = frappe.get_all(
			"ToDo", filters={"reference_type": "Task", "reference_name": self.task.name}, pluck="name"
		)[0]
		set_status(
			"Task", self.task.name, todo=todo, assign_to=self.USER,
			status="Cancelled", ignore_permissions=True,
		)
		self._set_status("Open")
		self.assertEqual(_statuses("Task", self.task.name), ["Cancelled"])
