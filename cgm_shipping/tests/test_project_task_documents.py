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


def _run(tasks, files, readable=None):
    """All the shipment's tasks come from get_all; the readable ones from get_list.

    `readable` is the set of task names this user could open. Anything outside it is
    visible only when the task is not Finance's.
    """
    names = [t["name"] for t in tasks] if readable is None else list(readable)

    def get_all(doctype, **kw):
        if doctype == "Task":
            return [frappe._dict(t) for t in tasks]
        # Honour the filter the way the database would, or a hidden task's file
        # would come back and the test would pass on a stub, not on the code.
        wanted = set((kw.get("filters") or {}).get("attached_to_name", ["in", []])[1])
        return [frappe._dict(f) for f in files if f["attached_to_name"] in wanted]

    with (
        patch.object(frappe, "has_permission", return_value=True),
        patch.object(frappe, "get_all", side_effect=get_all),
        patch.object(
            frappe, "get_list", return_value=[frappe._dict(name=n) for n in names]
        ),
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
        """A task deleted between the two queries must not drop its file silently.

        Stubbed without the filter on purpose: the point is the lookup missing, which
        the filter would otherwise make unreachable.
        """
        orphan = frappe._dict(FILES[0], attached_to_name="TASK-GONE")

        def get_all(doctype, **kw):
            if doctype == "Task":
                return [frappe._dict(t) for t in TASKS]
            return [orphan]

        with (
            patch.object(frappe, "has_permission", return_value=True),
            patch.object(frappe, "get_all", side_effect=get_all),
            patch.object(frappe, "get_list", return_value=[]),
        ):
            rows = ptd.get_project_task_documents("PROJ-0001")["rows"]
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


class TestWhoSeesTheShipmentPack(unittest.TestCase):
    """The pack is for whoever works the shipment; Finance's evidence is not.

    Scoping this by Task department was wrong for this panel. Every permit, IDF and
    entry on a shipment sits on a Declaration task, so a field officer - the person
    who carries those papers to the port - opened the shipment and was told no files
    were attached. On PROJ-0034 all 12 files sat on Declaration tasks.

    Finance's payment evidence stays behind the task permission: a POP still only
    reaches somebody who can open the task holding it.
    """

    def test_a_declaration_document_reaches_someone_who_cannot_open_that_task(self):
        """This is the field officer case."""
        rows = _run(TASKS, FILES, readable=[])["rows"]
        self.assertIn("entry.pdf", [r["file_name"] for r in rows])

    def test_finance_evidence_stays_with_finance(self):
        rows = _run(TASKS, FILES, readable=[])["rows"]
        self.assertNotIn("receipt.pdf", [r["file_name"] for r in rows])

    def test_finance_still_sees_its_own(self):
        rows = _run(TASKS, FILES, readable=["TASK-1", "TASK-2"])["rows"]
        self.assertEqual(
            sorted(r["file_name"] for r in rows), ["entry.pdf", "receipt.pdf"]
        )

    def test_a_permit_finance_task_is_treated_as_finance_too(self):
        tasks = [
            {
                "name": "TASK-9",
                "subject": "Finance pays permits",
                "custom_task_role": "Permit Finance",
            }
        ]
        files = [dict(FILES[0], attached_to_name="TASK-9")]
        self.assertEqual(_run(tasks, files, readable=[])["total"], 0)

    def test_the_file_query_never_asks_for_a_hidden_task(self):
        with (
            patch.object(frappe, "has_permission", return_value=True),
            patch.object(frappe, "get_list", return_value=[]),
            patch.object(
                frappe, "get_all", side_effect=[[frappe._dict(t) for t in TASKS], []]
            ) as get_all,
        ):
            ptd.get_project_task_documents("PROJ-0001")
        asked = get_all.call_args.kwargs["filters"]["attached_to_name"][1]
        self.assertEqual(asked, ["TASK-2"])

    def test_the_count_matches_what_the_panel_lists(self):
        with (
            patch.object(frappe, "has_permission", return_value=True),
            patch.object(
                frappe, "get_all", return_value=[frappe._dict(t) for t in TASKS]
            ),
            patch.object(frappe, "get_list", return_value=[]),
            patch.object(frappe.db, "count", return_value=1) as count,
        ):
            self.assertEqual(ptd.task_document_count("PROJ-0001"), 1)
        self.assertEqual(count.call_args[0][1]["attached_to_name"][1], ["TASK-2"])
