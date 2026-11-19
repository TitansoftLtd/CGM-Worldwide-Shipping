"""An import container is not asked export questions, and a re-upload replaces."""

import json
import pathlib
import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import task_attachments as ta

TRACKER_JSON = pathlib.Path(__file__).resolve().parents[1] / (
    "cgm_worldwide_shipping/doctype/container_tracker/container_tracker.json"
)
IMPORT_MODES = ("Mombasa Port", "ICD Nairobi", "Transit Import")
EXPORT_MODES = ("Transit Export", "Export")


def _modes_named_in_rules() -> set[str]:
    """Every container mode the stored rules mention."""
    names = set()
    for expr in _rules().values():
        if "].includes" not in expr:
            continue  # a rule about a field's value, not about the mode
        body = expr[len("eval:") :].lstrip("!")
        names.update(json.loads(body[: body.index("].includes") + 1]))
    return names


def _rules() -> dict[str, str]:
    data = json.loads(TRACKER_JSON.read_text())
    return {f["fieldname"]: f["depends_on"] for f in data["fields"] if f.get("depends_on")}


def _shows(expr: str, mode: str) -> bool:
    """Evaluate the stored eval: rule the way the browser would."""
    body = expr[len("eval:") :]
    in_list = lambda names: mode in names  # noqa: E731
    if body.startswith("!"):
        return not in_list(json.loads(body[1 : body.index("].includes") + 1]))
    return in_list(json.loads(body[: body.index("].includes") + 1]))


class TestTheRulesNameRealModes(unittest.TestCase):
    """A renamed mode must fail here, not quietly stop matching on the form."""

    def test_every_mode_in_a_rule_is_a_seeded_mode(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
            CONTAINER_TRACKER_MODES,
        )

        seeded = {row["mode_name"] for row in CONTAINER_TRACKER_MODES}
        unknown = sorted(_modes_named_in_rules() - seeded)
        self.assertEqual(unknown, [], "Container Tracker rules name modes that do not exist")

    def test_this_test_covers_the_modes_the_others_assume(self):
        """IMPORT_MODES and EXPORT_MODES are the same list, split by direction."""
        from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
            CONTAINER_TRACKER_MODES,
        )

        seeded = {row["mode_name"] for row in CONTAINER_TRACKER_MODES}
        self.assertEqual(set(IMPORT_MODES) | set(EXPORT_MODES), seeded)


class TestContainerSectionsByMode(unittest.TestCase):
    def test_export_section_is_hidden_on_every_import_mode(self):
        rule = _rules()["section_export"]
        for mode in IMPORT_MODES:
            self.assertFalse(_shows(rule, mode), mode)

    def test_export_section_shows_on_export_modes(self):
        rule = _rules()["section_export"]
        for mode in EXPORT_MODES:
            self.assertTrue(_shows(rule, mode), mode)

    def test_transit_section_only_on_transit(self):
        rule = _rules()["section_transit"]
        self.assertFalse(_shows(rule, "Mombasa Port"))
        self.assertFalse(_shows(rule, "Export"))
        self.assertTrue(_shows(rule, "Transit Import"))
        self.assertTrue(_shows(rule, "Transit Export"))

    def test_import_only_tabs_hide_on_export(self):
        rules = _rules()
        for fieldname in ("free_days_tab", "empty_return_and_interchange_tab", "section_mombasa"):
            self.assertTrue(_shows(rules[fieldname], "Mombasa Port"), fieldname)
            self.assertFalse(_shows(rules[fieldname], "Export"), fieldname)

    def test_a_blank_mode_is_treated_as_import(self):
        """503 of 503 live containers have a mode, but a new row starts blank."""
        rules = _rules()
        self.assertTrue(_shows(rules["section_mombasa"], ""))
        self.assertFalse(_shows(rules["section_export"], ""))

    def test_the_icd_section_is_left_alone(self):
        """An import landed at Mombasa can still move to an ICD."""
        self.assertNotIn("section_icd", _rules())


class TestTheRollUpCollapsesRepeats(unittest.TestCase):
    def test_the_same_file_twice_on_one_task_is_one_row(self):
        rows = [
            {"task": "T1", "file_url": "/files/a.pdf", "uploaded_on": "3"},
            {"task": "T1", "file_url": "/files/a.pdf", "uploaded_on": "2"},
            {"task": "T1", "file_url": "/files/a.pdf", "uploaded_on": "1"},
        ]
        out = ta.newest_per_file(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["uploaded_on"], "3", "the newest is kept")

    def test_a_different_file_on_the_same_task_is_kept(self):
        rows = [
            {"task": "T1", "file_url": "/files/a.pdf"},
            {"task": "T1", "file_url": "/files/b.pdf"},
        ]
        self.assertEqual(len(ta.newest_per_file(rows)), 2)

    def test_the_same_file_on_two_tasks_is_kept(self):
        rows = [
            {"task": "T1", "file_url": "/files/a.pdf"},
            {"task": "T2", "file_url": "/files/a.pdf"},
        ]
        self.assertEqual(len(ta.newest_per_file(rows)), 2)


class TestAReuploadReplaces(unittest.TestCase):
    def _file(self, **kw):
        base = {"name": "F3", "attached_to_doctype": "Task", "attached_to_name": "T1",
                "file_url": "/files/a.pdf"}
        base.update(kw)
        return frappe._dict(base)

    def _run(self, existing, **kw):
        rows = [frappe._dict(r) for r in existing]
        with (
            patch.object(frappe, "get_all", return_value=rows),
            patch.object(frappe.db, "delete") as deleted,
            patch.object(frappe, "delete_doc") as lifecycle,
        ):
            ta.drop_superseded_task_attachment(self._file(**kw))
            # on_trash would comment "Attachment Removed" on the task; nothing was.
            lifecycle.assert_not_called()
        return [c.args[1]["name"] for c in deleted.call_args_list]

    def test_earlier_copies_go_and_the_newest_stays(self):
        gone = self._run([{"name": "F3"}, {"name": "F2"}, {"name": "F1"}])
        self.assertEqual(gone, ["F2", "F1"])

    def test_a_single_upload_deletes_nothing(self):
        self.assertEqual(self._run([{"name": "F1"}], name="F1"), [])

    def test_the_upload_survives_a_row_that_sorts_before_it(self):
        """Keep the upload that triggered the hook, not whichever row comes first.

        A row whose creation sits in the future, from an import or clock skew,
        used to be kept while the record the user had just made was deleted.
        """
        gone = self._run([{"name": "F_FUTURE"}, {"name": "F3"}], name="F3")
        self.assertEqual(gone, ["F_FUTURE"])

    def test_attachments_on_other_doctypes_are_untouched(self):
        with patch.object(frappe, "get_all") as looked:
            ta.drop_superseded_task_attachment(
                self._file(attached_to_doctype="Project", attached_to_name="PROJ-1")
            )
        looked.assert_not_called()

    def test_a_file_with_no_task_is_ignored(self):
        with patch.object(frappe, "get_all") as looked:
            ta.drop_superseded_task_attachment(self._file(attached_to_name=None))
        looked.assert_not_called()

    def test_a_read_failure_leaves_the_duplicate_alone(self):
        with (
            patch.object(frappe, "get_all", side_effect=Exception("db down")),
            patch.object(frappe, "log_error"),
            patch.object(frappe.db, "delete") as deleted,
        ):
            ta.drop_superseded_task_attachment(self._file())
        deleted.assert_not_called()


class TestTheCleanupPatch(unittest.TestCase):
    def _run(self, rows):
        got = []
        with (
            patch.object(frappe, "get_all", return_value=[frappe._dict(r) for r in rows]),
            patch.object(frappe.db, "delete", side_effect=lambda dt, f: got.append(f["name"])),
        ):
            n = ta.drop_existing_duplicate_task_attachments()
        return n, got

    def test_keeps_the_newest_of_each_group(self):
        """get_all is ordered newest first, so the first of each group survives."""
        n, got = self._run([
            {"name": "F3", "attached_to_name": "T1", "file_url": "/a.pdf", "content_hash": "h", "creation": "3"},
            {"name": "F2", "attached_to_name": "T1", "file_url": "/a.pdf", "content_hash": "h", "creation": "2"},
            {"name": "F1", "attached_to_name": "T1", "file_url": "/a.pdf", "content_hash": "h", "creation": "1"},
        ])
        self.assertEqual((n, got), (2, ["F2", "F1"]))

    def test_a_changed_file_reusing_a_name_is_left_alone(self):
        n, got = self._run([
            {"name": "F2", "attached_to_name": "T1", "file_url": "/a.pdf", "content_hash": "new", "creation": "2"},
            {"name": "F1", "attached_to_name": "T1", "file_url": "/a.pdf", "content_hash": "old", "creation": "1"},
        ])
        self.assertEqual((n, got), (0, []))

    def test_a_group_with_no_hash_is_left_alone(self):
        n, got = self._run([
            {"name": "F2", "attached_to_name": "T1", "file_url": "/a.pdf", "content_hash": None, "creation": "2"},
            {"name": "F1", "attached_to_name": "T1", "file_url": "/a.pdf", "content_hash": None, "creation": "1"},
        ])
        self.assertEqual((n, got), (0, []))

    def test_different_tasks_are_separate_groups(self):
        n, got = self._run([
            {"name": "F2", "attached_to_name": "T2", "file_url": "/a.pdf", "content_hash": "h", "creation": "2"},
            {"name": "F1", "attached_to_name": "T1", "file_url": "/a.pdf", "content_hash": "h", "creation": "1"},
        ])
        self.assertEqual((n, got), (0, []))

    def test_running_it_twice_removes_nothing_the_second_time(self):
        n, _ = self._run([
            {"name": "F1", "attached_to_name": "T1", "file_url": "/a.pdf", "content_hash": "h", "creation": "1"},
        ])
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
