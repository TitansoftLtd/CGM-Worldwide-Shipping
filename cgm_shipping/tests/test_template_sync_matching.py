"""Template saves re-stamp an open task only from the row it came from.

The sync used to match template rows to tasks by step number alone. When the
Road Transit template grew from 9 to 13 steps, every open task on PROJ-0035 was
re-stamped with whatever role now sat at its step - "Taxes paid" became Permit
Finance, "Book trucks and obtain C2" a Permit Application.
"""

import unittest

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
	template_item_for_task,
)

ITEMS = [
	{"sequence_no": 4, "subject": "Apply for pre-clearance permits", "task_role": "Permit Application"},
	{"sequence_no": 5, "subject": "Finance pays pre-clearance permits", "task_role": "Permit Finance"},
	{"sequence_no": 6, "subject": "Lodge border or ICD entry", "task_role": "Application"},
	{"sequence_no": 11, "subject": "Book trucks", "task_role": "Standard"},
	{"sequence_no": 12, "subject": "Book trucks", "task_role": "Document"},
]


def _task(subject, seq):
	return frappe._dict(subject=subject, custom_sequence_no=seq)


class TestTemplateItemForTask(unittest.TestCase):
	def test_moved_row_is_found_by_subject(self):
		item = template_item_for_task(_task("Lodge border or ICD entry", 4), ITEMS)
		self.assertEqual(item["sequence_no"], 6)

	def test_step_number_alone_never_matches(self):
		"""PROJ-0035: step 5 is now another row - the task must keep its stamps."""
		self.assertIsNone(template_item_for_task(_task("Taxes paid", 5), ITEMS))

	def test_repeated_subject_needs_the_same_step(self):
		self.assertEqual(template_item_for_task(_task("Book trucks", 12), ITEMS)["task_role"], "Document")
		self.assertIsNone(template_item_for_task(_task("Book trucks", 13), ITEMS))

	def test_case_and_spacing_are_ignored(self):
		item = template_item_for_task(_task("  apply for PRE-clearance   permits ", 4), ITEMS)
		self.assertEqual(item["sequence_no"], 4)

	def test_blank_subject_matches_nothing(self):
		self.assertIsNone(template_item_for_task(_task("", 4), ITEMS))
