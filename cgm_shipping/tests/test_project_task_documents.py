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
    """Tasks come from get_list, which applies Task permissions; files from get_all."""
    with (
        patch.object(frappe, "has_permission", return_value=True),
        patch.object(frappe, "get_list", return_value=[frappe._dict(t) for t in tasks]),
        patch.object(frappe, "get_all", return_value=[frappe._dict(f) for f in files]),
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
            patch.object(frappe, "get_list", return_value=[]),
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


class TestItOnlyShowsFilesFromTasksTheUserMayRead(unittest.TestCase):
    """Reading the shipment used to hand over every task's files.

    Task visibility is narrowed by department and assignment, but the task list was
    built with get_all, which ignores permissions. On real data one operations user
    could read 7 of a shipment's 23 tasks and was still shown all 56 files, finance
    payment proofs included.
    """

    def test_files_on_unreadable_tasks_are_left_out(self):
        readable = [TASKS[0]]
        with (
            patch.object(frappe, "has_permission", return_value=True),
            patch.object(frappe, "get_list", return_value=[frappe._dict(t) for t in readable]),
            patch.object(frappe, "get_all", return_value=[frappe._dict(FILES[0])]),
        ) :
            result = ptd.get_project_task_documents("PROJ-0001")
        self.assertEqual([r["task"] for r in result["rows"]], ["TASK-1"])

    def test_the_file_query_is_limited_to_readable_tasks(self):
        """The unreadable task must not even reach the File filter."""
        with (
            patch.object(frappe, "has_permission", return_value=True),
            patch.object(frappe, "get_list", return_value=[frappe._dict(TASKS[0])]),
            patch.object(frappe, "get_all", return_value=[]) as get_all,
        ):
            ptd.get_project_task_documents("PROJ-0001")
        asked_for = get_all.call_args.kwargs["filters"]["attached_to_name"][1]
        self.assertEqual(asked_for, ["TASK-1"])

    def test_the_task_list_is_not_built_with_get_all(self):
        """get_all ignores permissions, so it must not be what lists the tasks."""
        with (
            patch.object(frappe, "has_permission", return_value=True),
            patch.object(frappe, "get_list", return_value=[]) as get_list,
            patch.object(frappe, "get_all", return_value=[]),
        ):
            ptd.get_project_task_documents("PROJ-0001")
        self.assertEqual(get_list.call_args[0][0], "Task")
        self.assertIs(get_list.call_args.kwargs["ignore_permissions"], False)

    def test_without_task_read_nothing_is_returned(self):
        """Readable shipment, no Task permission at all: empty, not every file."""
        def perm(doctype, *a, **kw):
            return doctype != "Task"

        with patch.object(frappe, "has_permission", side_effect=perm):
            self.assertEqual(
                ptd.get_project_task_documents("PROJ-0001"), {"rows": [], "total": 0}
            )

    def test_the_count_matches_what_the_panel_lists(self):
        """A badge counting more than the list shows would advertise hidden files."""
        with (
            patch.object(frappe, "has_permission", return_value=True),
            patch.object(frappe, "get_list", return_value=[frappe._dict(TASKS[0])]),
            patch.object(frappe.db, "count", return_value=1) as count,
        ):
            self.assertEqual(ptd.task_document_count("PROJ-0001"), 1)
        self.assertEqual(count.call_args[0][1]["attached_to_name"][1], ["TASK-1"])
