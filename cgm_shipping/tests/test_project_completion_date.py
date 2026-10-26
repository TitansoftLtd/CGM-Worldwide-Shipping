"""A shipment records the day it finished, so a month can be reported on.

`custom_shipment_status` said whether a shipment was finished but never when, so
"which shipments completed in September" had no answer. The date written is the day
the last task was completed, not the day someone got round to setting the status.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import project_completion as pc


def _project(status="Completed", completion_date=None, has_field=True):
	doc = frappe._dict(name="PROJ-TEST", custom_shipment_status=status, custom_completion_date=completion_date)
	doc.meta = frappe._dict(has_field=lambda fieldname: has_field)
	doc.written = {}
	doc.db_set = lambda field, value, update_modified=True: doc.written.__setitem__(field, value)
	return doc


class TestProjectCompletionDate(unittest.TestCase):
	def _run(self, doc, last_task="2026-09-18"):
		with patch.object(pc, "last_task_completion_date", return_value=last_task):
			pc.set_completion_date_on_update(doc)
		return doc.written

	def test_completed_shipment_is_stamped_with_the_last_task_date(self):
		written = self._run(_project(status="Completed"))
		self.assertEqual(written, {"custom_completion_date": "2026-09-18"})

	def test_settled_also_counts_as_finished(self):
		written = self._run(_project(status="Settled"))
		self.assertEqual(written["custom_completion_date"], "2026-09-18")

	def test_a_shipment_still_running_is_not_stamped(self):
		self.assertEqual(self._run(_project(status="Pre-clearance")), {})

	def test_an_existing_date_is_never_overwritten(self):
		# Re-saving a finished shipment must not move the date to the latest task.
		self.assertEqual(self._run(_project(status="Completed", completion_date="2026-08-01")), {})

	def test_reopening_clears_the_date(self):
		written = self._run(_project(status="Pre-clearance", completion_date="2026-09-18"))
		self.assertEqual(written, {"custom_completion_date": None})

	def test_a_site_without_the_field_is_left_alone(self):
		self.assertEqual(self._run(_project(has_field=False)), {})


class TestLastTaskCompletionDate(unittest.TestCase):
	def test_the_latest_completed_task_date_is_used(self):
		with patch.object(frappe.db, "sql", return_value=[["2026-09-30"]]):
			self.assertEqual(pc.last_task_completion_date("PROJ-TEST"), "2026-09-30")

	def test_no_dated_task_falls_back_to_today(self):
		# `nowdate` is patched too: it reads System Settings, which would go through the
		# patched `sql` and fail for reasons that have nothing to do with this.
		with (
			patch.object(frappe.db, "sql", return_value=[[None]]),
			patch.object(pc, "nowdate", return_value="2026-10-26"),
		):
			self.assertEqual(pc.last_task_completion_date("PROJ-TEST"), "2026-10-26")


class TestSyncFromTheTaskDrivenWrite(unittest.TestCase):
	"""`sea_clearance` advances the status with `db.set_value`, running no hooks.

	That is the path that finishes most shipments, so it has to reconcile the date
	itself. These cover the same four cases as the document hook, one layer down.
	"""

	def _sync(self, status, recorded, last_task="2026-09-18"):
		written = {}
		with (
			patch.object(frappe, "get_meta", return_value=frappe._dict(has_field=lambda f: True)),
			patch.object(frappe.db, "get_value", return_value=recorded),
			patch.object(frappe.db, "set_value", side_effect=lambda dt, n, f, v, **kw: written.__setitem__(f, v)),
			patch.object(pc, "last_task_completion_date", return_value=last_task),
		):
			pc.sync_completion_date("PROJ-TEST", status)
		return written

	def test_finishing_stamps_the_last_task_date(self):
		self.assertEqual(self._sync("Completed", None), {"custom_completion_date": "2026-09-18"})

	def test_an_existing_date_is_left_alone(self):
		self.assertEqual(self._sync("Completed", "2026-08-01"), {})

	def test_a_status_short_of_finished_stamps_nothing(self):
		self.assertEqual(self._sync("Pre-clearance", None), {})

	def test_moving_back_clears_the_date(self):
		self.assertEqual(self._sync("Pre-clearance", "2026-09-18"), {"custom_completion_date": None})
