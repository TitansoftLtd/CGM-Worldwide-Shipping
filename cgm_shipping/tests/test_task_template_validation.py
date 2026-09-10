"""CGM Task Template validation.

Every task a project gets is stamped from a template row. A bad row does not
fail at save time on its own - it surfaces later as a task nobody can see, a
dependency that never links, or a step that waits forever for a condition that
cannot be met. These tests pin the checks that turn those into save errors.
"""

import unittest

import frappe

TEMPLATE = "Sea Import Workflow"


def _template():
	return frappe.get_doc("CGM Task Template", TEMPLATE)


class TestTaskTemplateValidation(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		if not frappe.db.exists("CGM Task Template", TEMPLATE):
			raise unittest.SkipTest(f"{TEMPLATE} not present on this site")

	def setUp(self):
		frappe.flags.mute_messages = True

	def tearDown(self):
		frappe.flags.mute_messages = False
		frappe.db.rollback()

	def test_shipped_templates_validate(self):
		"""Every template on the site must still save - checks that warn, not block."""
		for name in frappe.get_all("CGM Task Template", pluck="name"):
			with self.subTest(template=name):
				frappe.get_doc("CGM Task Template", name).validate()

	def test_duplicate_sequence_rejected(self):
		doc = _template()
		doc.tasks[1].sequence_no = doc.tasks[0].sequence_no
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_dangling_dependency_rejected(self):
		doc = _template()
		doc.tasks[3].depends_on_sequences = "999"
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_self_dependency_rejected(self):
		doc = _template()
		doc.tasks[3].depends_on_sequences = str(doc.tasks[3].sequence_no)
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_unknown_department_rejected(self):
		doc = _template()
		doc.tasks[0].department_role = "Fnance"
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_permit_row_needs_stage(self):
		doc = _template()
		row = next(
			(r for r in doc.tasks if r.task_role in ("Permit Application", "Permit Finance")),
			None,
		)
		if not row:
			self.skipTest("no permit rows in this template")
		row.permit_stage = ""
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_completion_condition_must_be_a_real_project_field(self):
		doc = _template()
		doc.tasks[0].completion_condition = "project.not_a_real_field"
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_completion_condition_must_be_well_formed(self):
		doc = _template()
		doc.tasks[0].completion_condition = "doc.something"
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_unknown_document_type_rejected(self):
		doc = _template()
		doc.tasks[2].required_document_types = "NOT_A_DOCUMENT_TYPE"
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_document_types_canonicalised(self):
		"""Accepted names are rewritten so template, stamp and gate agree."""
		names = frappe.get_all("Document Type", pluck="name", limit=2)
		if len(names) < 2:
			self.skipTest("need at least two Document Types")
		doc = _template()
		doc.tasks[2].required_document_types = f"{names[0]} ,{names[1]}"
		doc.validate()
		self.assertEqual(doc.tasks[2].required_document_types, f"{names[0]}, {names[1]}")

	def _warnings(self, doc) -> list[str]:
		"""Titles of the msgprints a save would raise.

		setUp mutes messages so the other tests stay quiet; unmute here or
		msgprint drops them and every assertion below sees an empty log.
		"""
		frappe.flags.mute_messages = False
		frappe.message_log = []
		try:
			doc.validate()
			return [frappe.parse_json(m).get("title") for m in frappe.message_log]
		finally:
			frappe.flags.mute_messages = True

	def test_missing_payment_kind_warns_but_saves(self):
		"""Degrades a step rather than corrupting it - must not block an edit."""
		doc = _template()
		row = next((r for r in doc.tasks if r.task_role == "Finance Payment"), None)
		if not row:
			self.skipTest("no finance rows in this template")
		row.payment_kind = ""
		self.assertIn("Missing Payment Kind", self._warnings(doc))

	def test_pairing_warnings_silent_without_application_rows(self):
		"""Export plans have finance steps and no Application rows.

		Payment Kind means nothing there - Finance just records the payment - so
		the pairing warnings must not nag on every save of those templates.
		"""
		doc = _template()
		for row in doc.tasks:
			if row.task_role == "Application":
				row.task_role = "Document"
				row.payment_kind = ""
		titles = self._warnings(doc)
		self.assertNotIn("Missing Payment Kind", titles)
		self.assertNotIn("Unpaired Finance Task", titles)

	def test_no_warnings_on_shipped_templates(self):
		"""Saving any template as it ships must be silent.

		Except Sea Import's Client Inspection gate, which points at a step the plan
		no longer has (test_template_gates.KNOWN_MISSING_STEPS). The warning stays
		until someone decides which task reaches that status.
		"""
		known = {TEMPLATE: ["Unreachable Status"]}
		for name in frappe.get_all("CGM Task Template", pluck="name"):
			with self.subTest(template=name):
				self.assertEqual(
					self._warnings(frappe.get_doc("CGM Task Template", name)), known.get(name, [])
				)
