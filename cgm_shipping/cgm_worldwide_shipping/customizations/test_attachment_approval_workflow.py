# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow import (
	get_profile,
	sync_workflow_on_attachment_change,
	validate_workflow_on_parent_save,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	APPROVAL_STATUS_APPROVED,
	APPROVAL_STATUS_DRAFT,
	APPROVAL_STATUS_PENDING_REVIEW,
	APPROVAL_STATUS_REJECTED,
	FINAL_DOCUMENT_WORKFLOW_ACTION_APPROVE,
	FINAL_DOCUMENT_WORKFLOW_ACTION_REJECT,
	FINAL_DOCUMENT_WORKFLOW_ACTION_SEND,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.final_document_workflow import (
	apply_final_document_workflow_transition,
	final_document_status,
	get_available_final_document_actions,
	sync_final_document_workflow_on_attachment_change,
)


class TestAttachmentApprovalWorkflow(UnitTestCase):
	def _row(self, **values):
		row = frappe._dict(
			final_attachment="/files/final.pdf",
			final_document_status=APPROVAL_STATUS_DRAFT,
			final_document_approved_by=None,
			final_document_approved_on=None,
		)
		row.meta = frappe.get_meta("Shipment Document")
		row.doctype = "Shipment Document"
		row.update(values)
		return row

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow._route_parent_for_review"
	)
	@patch("frappe.has_permission", return_value=True)
	def test_send_for_review_sets_pending_status(self, _permission, _route):
		parent = frappe._dict(doctype="Task", name="TASK-TEST")
		row = self._row(parentfield="custom_task_documents")
		apply_final_document_workflow_transition(parent, row, FINAL_DOCUMENT_WORKFLOW_ACTION_SEND)
		self.assertEqual(row.final_document_status, APPROVAL_STATUS_PENDING_REVIEW)

	def test_attachment_replace_resets_workflow(self):
		row = self._row(
			final_document_status=APPROVAL_STATUS_APPROVED,
			final_document_approved_by="user@example.com",
			final_document_approved_on="2026-01-01 10:00:00",
			final_attachment="/files/final-v2.pdf",
		)
		prev = self._row(final_attachment="/files/final.pdf")
		sync_final_document_workflow_on_attachment_change(row, prev)
		self.assertEqual(row.final_document_status, APPROVAL_STATUS_DRAFT)
		self.assertIsNone(row.final_document_approved_by)
		self.assertIsNone(row.final_document_approved_on)

	def test_no_row_level_actions_exposed(self):
		parent = frappe._dict(doctype="Task", name="TASK-TEST")
		row = self._row()
		actions = get_available_final_document_actions(parent, row)
		self.assertEqual(actions, [])

	def test_default_status_is_draft(self):
		row = self._row(final_document_status="")
		self.assertEqual(final_document_status(row), APPROVAL_STATUS_DRAFT)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.permissions.user_has_operations_department_access",
		return_value=True,
	)
	def test_approve_sets_approval_metadata(self, _review):
		parent = frappe._dict(doctype="Task", name="TASK-TEST")
		row = self._row(
			final_document_status=APPROVAL_STATUS_PENDING_REVIEW,
			parentfield="custom_task_documents",
		)
		apply_final_document_workflow_transition(parent, row, FINAL_DOCUMENT_WORKFLOW_ACTION_APPROVE)
		self.assertEqual(row.final_document_status, APPROVAL_STATUS_APPROVED)
		self.assertEqual(row.final_document_approved_by, frappe.session.user)
		self.assertIsNotNone(row.final_document_approved_on)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.permissions.user_has_operations_department_access",
		return_value=True,
	)
	def test_reject_clears_approval_metadata(self, _review):
		parent = frappe._dict(doctype="Task", name="TASK-TEST")
		row = self._row(
			final_document_status=APPROVAL_STATUS_PENDING_REVIEW,
			final_document_approved_by="user@example.com",
			final_document_approved_on="2026-01-01 10:00:00",
			parentfield="custom_task_documents",
		)
		apply_final_document_workflow_transition(parent, row, FINAL_DOCUMENT_WORKFLOW_ACTION_REJECT)
		self.assertEqual(row.final_document_status, APPROVAL_STATUS_REJECTED)
		self.assertIsNone(row.final_document_approved_by)

	@patch(
		"cgm_shipping.cgm_worldwide_shipping.customizations.permissions.user_has_operations_department_access",
		return_value=True,
	)
	def test_approve_clears_rejection_reason(self, _review):
		from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow import (
			ParentTableBinding,
			_apply_transition,
		)

		parent = frappe._dict(doctype="Task", name="TASK-TEST")
		row = self._row(
			final_document_status=APPROVAL_STATUS_PENDING_REVIEW,
			reason_for_rejection="Wrong format",
			parentfield="custom_task_documents",
		)
		profile = get_profile("shipment_final_document")
		binding = ParentTableBinding(
			parent_doctype="Task",
			table_field="custom_task_documents",
			child_doctype="Shipment Document",
			profile_key=profile.key,
		)
		_apply_transition(parent, binding, profile, row, FINAL_DOCUMENT_WORKFLOW_ACTION_APPROVE)
		self.assertEqual(row.final_document_status, APPROVAL_STATUS_APPROVED)
		self.assertIsNone(row.reason_for_rejection)

	def test_attachment_replace_clears_rejection_reason(self):
		profile = get_profile("shipment_final_document")
		row = self._row(
			final_document_status=APPROVAL_STATUS_REJECTED,
			reason_for_rejection="Wrong format",
			final_attachment="/files/final-v2.pdf",
		)
		prev = self._row(final_attachment="/files/final.pdf")
		sync_workflow_on_attachment_change(row, profile, prev)
		self.assertEqual(row.final_document_status, APPROVAL_STATUS_DRAFT)
		self.assertIsNone(row.reason_for_rejection)

	def test_cleared_attachment_clears_rejection_reason(self):
		profile = get_profile("shipment_final_document")
		row = self._row(
			final_document_status=APPROVAL_STATUS_REJECTED,
			reason_for_rejection="Wrong format",
			final_attachment="",
		)
		prev = self._row(final_attachment="/files/final.pdf")
		sync_workflow_on_attachment_change(row, profile, prev)
		self.assertEqual(row.final_document_status, APPROVAL_STATUS_DRAFT)
		self.assertIsNone(row.reason_for_rejection)

	def test_empty_to_draft_default_does_not_fail_validation(self):
		profile = get_profile("shipment_final_document")
		prev_row = self._row(final_document_status="")
		row = self._row(final_document_status=APPROVAL_STATUS_DRAFT)
		prev = frappe._dict(
			doctype="Task",
			name="TASK-TEST",
			custom_task_documents=[prev_row],
		)
		parent = frappe._dict(
			doctype="Task",
			name="TASK-TEST",
			custom_task_documents=[row],
		)
		parent.meta = frappe.get_meta("Task")
		parent.get_doc_before_save = lambda: prev
		validate_workflow_on_parent_save(parent, "custom_task_documents", profile)

	def test_profile_sync_on_generic_module(self):
		profile = get_profile("shipment_final_document")
		row = self._row(
			final_document_status=APPROVAL_STATUS_APPROVED,
			final_attachment="/files/final-v2.pdf",
		)
		prev = self._row(final_attachment="/files/final.pdf")
		sync_workflow_on_attachment_change(row, profile, prev)
		self.assertEqual(row.final_document_status, APPROVAL_STATUS_DRAFT)
