"""Finance can submit a task's draft Journal Entries from the task.

Make Payment creates the entry as a draft for Finance to check. The task form
lists the drafts linked from its permit rows, finance lines and own Journal
Entry field - only those the user may submit - and submits one on request.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import task as t


def _task(**fields):
	return frappe._dict(
		name="TASK-TEST",
		custom_task_permits=fields.get("permits", []),
		custom_task_finance_lines=fields.get("lines", []),
		custom_journal_entry=fields.get("own"),
	)


def _drafts(task, *, drafts, can_submit=lambda je: True):
	rows = [frappe._dict(name=je, total_debit=100, posting_date="2026-09-11") for je in drafts]
	with (
		patch.object(t, "is_sea_finance_payment_task", return_value=True),
		patch.object(frappe, "get_all", return_value=rows),
		patch.object(frappe, "has_permission", side_effect=lambda dt, ptype, doc=None: can_submit(doc)),
	):
		return t.draft_journal_entries_for_task(task)


class TestDraftJournalEntriesForTask(unittest.TestCase):
	def test_lists_drafts_from_every_link_with_labels(self):
		task = _task(
			permits=[
				frappe._dict(permit_type="DVS", journal_entry="JE-1"),
				frappe._dict(permit_type="VMD", is_amendment=1, journal_entry="JE-2"),
			],
			lines=[frappe._dict(line_label="UCR Invoice", journal_entry="JE-3")],
			own="JE-4",
		)
		out = _drafts(task, drafts=["JE-1", "JE-2", "JE-3", "JE-4"])
		self.assertEqual(
			[(d["journal_entry"], d["label"]) for d in out],
			[("JE-1", "DVS"), ("JE-2", "VMD (amendment)"), ("JE-3", "UCR Invoice"), ("JE-4", "")],
		)

	def test_submitted_entries_are_left_out(self):
		task = _task(permits=[frappe._dict(permit_type="DVS", journal_entry="JE-1"), frappe._dict(permit_type="NBA", journal_entry="JE-2")])
		out = _drafts(task, drafts=["JE-2"])  # JE-1 is already submitted
		self.assertEqual([d["journal_entry"] for d in out], ["JE-2"])

	def test_only_entries_the_user_may_submit(self):
		task = _task(permits=[frappe._dict(permit_type="DVS", journal_entry="JE-1"), frappe._dict(permit_type="NBA", journal_entry="JE-2")])
		out = _drafts(task, drafts=["JE-1", "JE-2"], can_submit=lambda je: je == "JE-2")
		self.assertEqual([d["journal_entry"] for d in out], ["JE-2"])

	def test_same_entry_on_two_links_is_offered_once(self):
		task = _task(lines=[frappe._dict(line_label="Invoice", journal_entry="JE-1")], own="JE-1")
		self.assertEqual(len(_drafts(task, drafts=["JE-1"])), 1)

	def test_no_links_means_no_query(self):
		with patch.object(t, "is_sea_finance_payment_task", return_value=True), patch.object(frappe, "get_all") as get_all:
			self.assertEqual(t.draft_journal_entries_for_task(_task()), [])
		get_all.assert_not_called()

	def test_application_tasks_get_no_submit_buttons(self):
		# Create Entry mirrors Finance's entry (TASK-2026-00134 / -00135 share ACC-JV-2026-00148).
		task = _task(lines=[frappe._dict(line_label="Entry Slip", journal_entry="JE-1")])
		with patch.object(t, "is_sea_finance_payment_task", return_value=False), patch.object(frappe, "get_all") as get_all:
			self.assertEqual(t.draft_journal_entries_for_task(task), [])
		get_all.assert_not_called()


class TestSubmitTaskJournalEntry(unittest.TestCase):
	def _submit(self, journal_entry, offered):
		task = MagicMock(name="task")
		je = MagicMock(name="je")
		je.name = journal_entry
		docs = {"Task": task, "Journal Entry": je}
		with (
			patch.object(frappe, "get_doc", side_effect=lambda dt, name: docs[dt]),
			patch.object(t, "draft_journal_entries_for_task", return_value=[{"journal_entry": j} for j in offered]),
			patch.object(frappe.db, "get_value", return_value="Completed"),
		):
			return t.submit_task_journal_entry("TASK-TEST", journal_entry), je

	def test_submits_a_draft_linked_to_the_task(self):
		result, je = self._submit("JE-1", offered=["JE-1"])
		je.submit.assert_called_once()
		self.assertEqual(result, {"journal_entry": "JE-1", "task_status": "Completed"})

	def test_refuses_an_entry_not_offered_for_this_task(self):
		with self.assertRaises(frappe.ValidationError):
			self._submit("JE-OTHER", offered=["JE-1"])
