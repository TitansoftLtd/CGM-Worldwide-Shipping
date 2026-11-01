"""A shipment can show every file attached to its tasks.

Frappe keeps an attachment on the one document it was attached to. On this site that is
the task: production holds 2,250 files on tasks against 10 on projects, so retracing a
shipment months later meant opening every task in turn. This gathers them for reading
without copying anything, because a copy would double the storage and would not notice a
file replaced on the task afterwards.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import project_task_documents as ptd


def _run(tasks, files):
    with (
        patch.object(frappe, "has_permission", return_value=True),
        patch.object(frappe, "get_all", side_effect=[
            [frappe._dict(t) for t in tasks],
            [frappe._dict(f) for f in files],
        ]),
    ):
        return ptd.get_project_task_documents("PROJ-0001")


TASKS = [
    {"name": "TASK-1", "subject": "Finance pays KPA", "custom_task_role": "Finance Payment"},
    {"name": "TASK-2", "subject": "Create Entry", "custom_task_role": "Application"},
]
FILES = [
    {"name": "f1", "file_name": "receipt.pdf", "file_url": "/files/receipt.pdf", "is_private": 0,
     "attached_to_name": "TASK-1", "owner": "accounts@x", "creation": "2026-10-23 14:00:00"},
    {"name": "f2", "file_name": "entry.pdf", "file_url": "/files/entry.pdf", "is_private": 1,
     "attached_to_name": "TASK-2", "owner": "declarant@x", "creation": "2026-10-22 09:00:00"},
]


class TestProjectTaskDocuments(unittest.TestCase):
    def test_every_task_attachment_is_gathered_onto_the_shipment(self):
        result = _run(TASKS, FILES)
        self.assertEqual(result["total"], 2)
        self.assertEqual([r["file_name"] for r in result["rows"]], ["receipt.pdf", "entry.pdf"])

    def test_each_row_names_the_task_it_belongs_to(self):
        """Without the task the list is just filenames, which is not a trail."""
        rows = {r["file_name"]: r for r in _run(TASKS, FILES)["rows"]}
        self.assertEqual(rows["receipt.pdf"]["task"], "TASK-1")
        self.assertEqual(rows["receipt.pdf"]["task_subject"], "Finance pays KPA")
        self.assertEqual(rows["entry.pdf"]["uploaded_by"], "declarant@x")

    def test_a_file_whose_task_vanished_still_lists(self):
        # Defensive: the file is real even if the task lookup misses it.
        orphan = [dict(FILES[0], attached_to_name="TASK-GONE")]
        rows = _run(TASKS, orphan)["rows"]
        self.assertEqual(rows[0]["task"], "TASK-GONE")
        self.assertEqual(rows[0]["task_subject"], "")

    def test_a_shipment_with_no_tasks_returns_nothing(self):
        with (
            patch.object(frappe, "has_permission", return_value=True),
            patch.object(frappe, "get_all", return_value=[]),
        ):
            self.assertEqual(ptd.get_project_task_documents("PROJ-0001"), {"rows": [], "total": 0})

    def test_no_project_is_not_an_error(self):
        self.assertEqual(ptd.get_project_task_documents(""), {"rows": [], "total": 0})

    def test_permission_is_checked_against_the_project(self):
        """The caller names a project, so the project is what must be permitted."""
        with patch.object(frappe, "has_permission", side_effect=frappe.PermissionError) as perm:
            with self.assertRaises(frappe.PermissionError):
                ptd.get_project_task_documents("PROJ-0001")
        self.assertEqual(perm.call_args[0][0], "Project")
