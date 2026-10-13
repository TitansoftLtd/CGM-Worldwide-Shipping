"""Document Trail warning rules.

Rules pinned here:

* Closed tasks last changed by one user within a few seconds are reported as
  one action. That is the only trace a bulk close leaves, because it writes
  with `frappe.db.set_value` and no history row exists (PROJ-0037: 22 of 23
  tasks at 10:44 on 5 Oct 2026).
* Tasks still carrying their creation timestamp are not a bulk close - every
  project creates its tasks together.
* A Completed task with no completion date did not go through the task steps.
* A Completed sea project that lists containers must have a tracker and a
  confirmed port arrival.
* A project worked normally raises nothing.
"""

import unittest

from cgm_shipping.cgm_worldwide_shipping.customizations import document_trail as dt


def _task(n, *, status="Completed", modified="2026-10-05 10:44:30", by="ops@x", completed_on=None):
	return {
		"name": f"TASK-{n}",
		"status": status,
		"creation": "2026-08-07 15:29:10",
		"modified": modified,
		"modified_by": by,
		"completed_on": completed_on,
	}


def _texts(warnings):
	return " | ".join(w["text"] for w in warnings)


class TestBulkTaskGroups(unittest.TestCase):
	def test_tasks_sharing_a_timestamp_are_one_group(self):
		tasks = [_task(i, modified=f"2026-10-05 10:44:3{i % 4}") for i in range(22)]
		groups = dt.bulk_task_groups(tasks)
		self.assertEqual(len(groups), 1)
		self.assertEqual(groups[0]["count"], 22)
		self.assertEqual(groups[0]["user"], "ops@x")

	def test_tasks_completed_on_different_days_are_not_grouped(self):
		tasks = [_task(i, modified=f"2026-09-{i + 1:02d} 09:00:00") for i in range(12)]
		self.assertEqual(dt.bulk_task_groups(tasks), [])

	def test_a_few_tasks_together_is_not_reported(self):
		self.assertEqual(dt.bulk_task_groups([_task(i) for i in range(4)]), [])

	def test_different_users_are_not_merged(self):
		tasks = [_task(i, by="a@x") for i in range(4)] + [_task(i + 4, by="b@x") for i in range(4)]
		self.assertEqual(dt.bulk_task_groups(tasks), [])

	def test_untouched_tasks_from_project_creation_are_ignored(self):
		tasks = [_task(i, modified="2026-08-07 15:29:11") for i in range(23)]
		self.assertEqual(dt.bulk_task_groups(tasks), [])

	def test_open_tasks_are_ignored(self):
		self.assertEqual(dt.bulk_task_groups([_task(i, status="Open") for i in range(10)]), [])


class TestProjectWarnings(unittest.TestCase):
	SEA_DONE = {"status": "Completed", "custom_mode_of_transport": "Sea", "custom_port_arrival_confirmed": 0}

	def test_force_closed_project_raises_every_relevant_warning(self):
		tasks = [_task(i) for i in range(22)] + [
			_task(99, modified="2026-09-30 08:00:00", completed_on="2026-09-30")
		]
		text = _texts(dt.project_warnings(self.SEA_DONE, tasks, 0, 1, {"ops@x": "Ops Mombasa"}))
		self.assertIn("22 of 23 tasks were last changed by Ops Mombasa", text)
		self.assertIn("22 completed task(s) have no completion date", text)
		self.assertIn("has no Container Tracker", text)
		self.assertIn("port arrival was never confirmed", text)

	def test_project_worked_normally_raises_nothing(self):
		tasks = [
			_task(i, modified=f"2026-09-{i + 1:02d} 09:00:00", completed_on=f"2026-09-{i + 1:02d}")
			for i in range(23)
		]
		project = {**self.SEA_DONE, "custom_port_arrival_confirmed": 1}
		self.assertEqual(dt.project_warnings(project, tasks, 2, 2), [])

	def test_completed_project_with_open_tasks(self):
		tasks = [_task(1, status="Open"), _task(2, completed_on="2026-09-01", modified="2026-09-01 09:00:00")]
		text = _texts(dt.project_warnings({"status": "Completed"}, tasks, 0, 0))
		self.assertIn("1 task(s) are still open", text)

	def test_open_project_without_tracker_is_not_a_warning(self):
		"""Trackers are created at port arrival; a shipment still at sea has none."""
		project = {"status": "Open", "custom_mode_of_transport": "Sea"}
		self.assertEqual(dt.project_warnings(project, [_task(1, status="Open")], 0, 3), [])

	def test_shipment_status_completed_counts_as_completed(self):
		project = {"status": "Open", "custom_shipment_status": "Completed", "custom_mode_of_transport": "Sea"}
		self.assertIn("has no Container Tracker", _texts(dt.project_warnings(project, [], 0, 1)))


class TestTaskWarnings(unittest.TestCase):
	def test_completed_without_date_is_flagged(self):
		self.assertEqual(len(dt.task_warnings(_task(1))), 1)

	def test_completed_with_date_is_clean(self):
		self.assertEqual(dt.task_warnings(_task(1, completed_on="2026-09-01")), [])

	def test_open_task_is_clean(self):
		self.assertEqual(dt.task_warnings(_task(1, status="Open")), [])
