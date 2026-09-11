"""A status worked out while opening a Task form reaches tabTask, or is not shown.

The form is fetched with a GET, which Frappe rolls back. TASK-2026-01209 showed
Completed on the form - the load healed it - while the list, reading tabTask,
kept Open. An editor's request is now committed when the load changed the
status; a viewer's form shows the stored status.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import task as t

STORED = {"status": "Open", "progress": 0, "completed_by": None, "completed_on": None}


class TestSettleStatusWorkedOutOnLoad(unittest.TestCase):
	def setUp(self):
		self.addCleanup(setattr, frappe.local.flags, "commit", False)
		frappe.local.flags.commit = False

	def _settle(self, *, method="GET", status_after="Completed", can_write=True):
		doc = frappe._dict(name="TASK-TEST", status="Completed", progress=100, completed_by="finance@example.com", completed_on="2026-09-11")
		doc.set = lambda field, value: doc.__setitem__(field, value)
		with (
			patch.object(frappe.local, "request", frappe._dict(method=method), create=True),
			patch.object(frappe.db, "get_value", return_value=status_after),
		):
			t._settle_status_worked_out_on_load(doc, dict(STORED), can_write)
		return doc

	def test_editor_get_that_changed_status_is_committed(self):
		self._settle()
		self.assertTrue(frappe.local.flags.commit)

	def test_unchanged_status_is_not_committed(self):
		self._settle(status_after="Open")
		self.assertFalse(frappe.local.flags.commit)

	def test_viewer_sees_the_stored_status(self):
		doc = self._settle(can_write=False)
		self.assertFalse(frappe.local.flags.commit)
		self.assertEqual(doc.status, "Open")
		self.assertEqual(doc.progress, 0)
		self.assertIsNone(doc.completed_on)

	def test_post_commits_on_its_own(self):
		self._settle(method="POST")
		self.assertFalse(frappe.local.flags.commit)


class TestTransporterPortalAccessDenied(unittest.TestCase):
	"""Opening /transporter without access crashed on exc.message (AttributeError)."""

	def test_permission_error_shows_access_denied(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import transporter_portal as tp

		# Runs as the test user, who is not Guest, so the access check is reached.
		# (Patching frappe.local.session deleted it on exit and broke later tests.)
		context = frappe._dict()
		with patch.object(
			tp, "require_transporter_portal_access", side_effect=frappe.PermissionError("No transporter access")
		):
			self.assertIsNone(tp.portal_context_base(context))
		self.assertFalse(context.is_transporter)
		self.assertIn("No transporter access", context.error_message)
