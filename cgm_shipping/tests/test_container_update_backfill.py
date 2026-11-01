"""Transport details entered after a step was signed off still reach its task grid.

The live sync skips Completed and Cancelled tasks. For a cell that already holds a
value that is correct: a finished task records what was done at the time, and rewriting
it would destroy the trail rather than complete it. A blank cell records nothing, and
that is the hole: details entered on the Container Tracker after the step was signed off
never reached the grid, so whoever opened the task months later chasing a late container
found nothing there.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import task_container_updates as tcu

TRACKER_SEQ = 7


def _row(**values):
    row = frappe._dict({"container_tracker": "CT-1"})
    row.update(values)
    row.set = lambda f, v: row.__setitem__(f, v)
    return row


def _task(status="Completed", rows=None):
    task = frappe._dict(name="TASK-1", status=status,
                        custom_container_updates=rows if rows is not None else [])
    task.meta = frappe._dict(has_field=lambda f: True)
    task.saved = []
    task.save = lambda **kw: task.saved.append(True)
    task.get = lambda f, default=None: task.__dict__.get(f, default) if f != "custom_container_updates" else task["custom_container_updates"]
    return task


def _run(task, tracker_values):
    tracker = frappe._dict({"name": "CT-1", "project": "PROJ-1", **tracker_values})
    with (
        patch.object(tcu, "_finished_backfill_fields",
                     return_value={TRACKER_SEQ: ("truck_number", "driver_name", "transporter")}),
        patch.object(tcu, "_container_step_task_rows",
                     return_value=[frappe._dict(name="TASK-1", container_seq=TRACKER_SEQ)]),
        patch.object(frappe, "get_doc", return_value=task),
    ):
        return tcu.backfill_finished_task_rows_from_tracker(tracker)


class TestFinishedTaskBackfill(unittest.TestCase):
    def test_a_blank_cell_is_filled_from_the_tracker(self):
        row = _row(truck_number=None, driver_name=None, transporter=None)
        task = _task(rows=[row])
        changed = _run(task, {"truck_number": "KBX 123A", "driver_name": "J. Mwangi", "transporter": "ACME"})
        self.assertEqual(changed, 1)
        self.assertEqual(row.truck_number, "KBX 123A")
        self.assertEqual(row.driver_name, "J. Mwangi")

    def test_a_recorded_value_is_never_overwritten(self):
        """The finished task is the record of what was done; it is not ours to rewrite."""
        row = _row(truck_number="KBX 999Z", driver_name=None, transporter=None)
        task = _task(rows=[row])
        _run(task, {"truck_number": "KBX 123A", "driver_name": "J. Mwangi", "transporter": "ACME"})
        self.assertEqual(row.truck_number, "KBX 999Z")
        self.assertEqual(row.driver_name, "J. Mwangi")

    def test_an_open_task_is_left_to_the_live_sync(self):
        """Doing it here too would mean two writes for one edit."""
        row = _row(truck_number=None)
        task = _task(status="Open", rows=[row])
        self.assertEqual(_run(task, {"truck_number": "KBX 123A"}), 0)
        self.assertIsNone(row.truck_number)

    def test_a_row_for_a_different_container_is_untouched(self):
        row = _row(truck_number=None)
        row.container_tracker = "CT-OTHER"
        task = _task(rows=[row])
        self.assertEqual(_run(task, {"truck_number": "KBX 123A"}), 0)
        self.assertIsNone(row.truck_number)

    def test_nothing_to_fill_means_no_save(self):
        row = _row(truck_number="KBX 1", driver_name="J", transporter="ACME")
        task = _task(rows=[row])
        self.assertEqual(_run(task, {"truck_number": "KBX 1", "driver_name": "J", "transporter": "ACME"}), 0)
        self.assertEqual(task.saved, [])

    def test_a_tracker_with_no_project_does_nothing(self):
        self.assertEqual(
            tcu.backfill_finished_task_rows_from_tracker(frappe._dict(name="CT-1", project=None)), 0)

    def test_it_stands_down_while_the_live_sync_is_running(self):
        """Both run on the same tracker save; the flag stops them colliding."""
        frappe.flags.cgm_syncing_tracker_to_task = True
        try:
            self.assertEqual(
                tcu.backfill_finished_task_rows_from_tracker(
                    frappe._dict(name="CT-1", project="PROJ-1")), 0)
        finally:
            frappe.flags.cgm_syncing_tracker_to_task = False
