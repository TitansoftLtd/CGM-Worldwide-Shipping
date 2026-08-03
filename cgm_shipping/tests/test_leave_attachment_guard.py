"""Guard the "Attachment Required" rule on leave types.

Sick leave is only meaningful to HR when a medical note comes with it. Leave Type
has no stock field for that, so the rule rests on four pieces that must stay in
step: a flag on Leave Type, an Attach field on Leave Application that reveals
itself from that flag, a doc_events hook, and the flag switched on for the sick
leave types. Drop any one and applications sail through with nothing attached --
silently, which is the dangerous part.

Run: bench --site <site> run-tests --app cgm_shipping --module cgm_shipping.tests.test_leave_attachment_guard
"""

import unittest

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.leave_application import (
	REQUIRES_ATTACHMENT_FIELD,
	SUPPORTING_DOCUMENT_FIELD,
	validate_required_attachment,
)

FLAGGED_LEAVE_TYPES = ["Sick Leave Full", "Sick Leave Half"]
FLAG_FIELD = "custom_attachment_required"


class FakeLeaveApplication(dict):
	"""Only what the validator touches -- no HRMS scaffolding to keep in step."""

	doctype = "Leave Application"

	def __init__(self, leave_type, supporting_document=None):
		super().__init__()
		self.leave_type = leave_type
		self[SUPPORTING_DOCUMENT_FIELD] = supporting_document


class TestLeaveAttachmentGuard(unittest.TestCase):
	def test_leave_type_carries_the_flag(self):
		self.assertTrue(
			frappe.get_meta("Leave Type").get_field(REQUIRES_ATTACHMENT_FIELD),
			f"Leave Type is missing {REQUIRES_ATTACHMENT_FIELD}, the flag the guard reads",
		)

	def test_supporting_document_field_is_on_the_form(self):
		df = frappe.get_meta("Leave Application").get_field(SUPPORTING_DOCUMENT_FIELD)
		self.assertIsNotNone(df, "Supporting Document field is missing from Leave Application")
		self.assertEqual(df.fieldtype, "Attach")
		self.assertEqual(
			df.depends_on,
			f"eval:doc.{FLAG_FIELD}",
			"field must reveal itself only for leave types that require a document",
		)
		self.assertEqual(
			df.mandatory_depends_on,
			f"eval:doc.{FLAG_FIELD}",
			"desk form must mark it mandatory for those leave types",
		)

	def test_flag_is_fetched_onto_the_application(self):
		# depends_on can only read fields on the document, so the Leave Type flag
		# has to be fetched across before the Attach field can react to it
		df = frappe.get_meta("Leave Application").get_field(FLAG_FIELD)
		self.assertIsNotNone(df, f"Leave Application is missing {FLAG_FIELD}")
		self.assertEqual(df.fetch_from, f"leave_type.{REQUIRES_ATTACHMENT_FIELD}")

	def test_hook_is_wired(self):
		hooks = frappe.get_hooks("doc_events").get("Leave Application", {})
		handlers = hooks.get("validate") or []
		if isinstance(handlers, str):
			handlers = [handlers]
		self.assertTrue(
			any(h.endswith("leave_application.validate_required_attachment") for h in handlers),
			"validate_required_attachment is not hooked -- the rule is desk-only without it",
		)

	def test_sick_leave_requires_an_attachment(self):
		for leave_type in FLAGGED_LEAVE_TYPES:
			with self.subTest(leave_type=leave_type):
				self.assertTrue(
					frappe.db.get_value("Leave Type", leave_type, REQUIRES_ATTACHMENT_FIELD),
					f"{leave_type} is no longer flagged Attachment Required",
				)

	def test_flagged_type_without_document_is_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			validate_required_attachment(FakeLeaveApplication(FLAGGED_LEAVE_TYPES[0]))

	def test_flagged_type_with_document_passes(self):
		validate_required_attachment(
			FakeLeaveApplication(FLAGGED_LEAVE_TYPES[0], "/files/medical-note.pdf")
		)

	def test_unflagged_type_is_unaffected(self):
		unflagged = frappe.get_all(
			"Leave Type", filters={REQUIRES_ATTACHMENT_FIELD: 0}, limit=1, pluck="name"
		)
		self.assertTrue(unflagged, "expected at least one leave type without the flag")
		validate_required_attachment(FakeLeaveApplication(unflagged[0]))
