"""Backward-compatible wrappers for Shipment Document final attachment approval.

Parent-form actions are implemented in attachment_approval_workflow.py.
"""

from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow import (
	get_profile,
	sync_workflow_on_attachment_change,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
	user_has_operations_department_access,
)

_SHIPMENT_PROFILE_KEY = "shipment_final_document"


def _profile():
	return get_profile(_SHIPMENT_PROFILE_KEY)


def final_document_status(row) -> str:
	from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow import (
		row_status,
	)

	return row_status(row, _profile())


def has_final_document_attachment(row) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow import (
		row_has_attachment,
	)

	return row_has_attachment(row, _profile())


def sync_final_document_workflow_on_attachment_change(row, prev_row=None) -> None:
	sync_workflow_on_attachment_change(row, _profile(), prev_row)


def ensure_final_document_status_defaults(rows: Iterable) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow import (
		ensure_status_defaults,
	)

	ensure_status_defaults(rows, _profile())


def validate_final_document_workflow_on_parent_save(parent_doc, table_field: str) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow import (
		bindings_for_parent_table,
		validate_workflow_on_parent_save,
	)

	for binding in bindings_for_parent_table(parent_doc.doctype, table_field):
		validate_workflow_on_parent_save(parent_doc, table_field, get_profile(binding.profile_key))


def apply_final_document_workflow_transition(parent_doc, row, action: str) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow import (
		ParentTableBinding,
		_apply_transition,
	)

	profile = _profile()
	table_field = row.parentfield or ""
	binding = ParentTableBinding(
		parent_doctype=parent_doc.doctype,
		table_field=table_field,
		child_doctype=row.doctype,
		profile_key=profile.key,
	)
	_apply_transition(parent_doc, binding, profile, row, action)


def get_available_final_document_actions(parent_doc, row, *, user: str | None = None) -> list[dict[str, str]]:
	return []


def _can_review_final_document() -> bool:
	return user_has_operations_department_access()


def _route_final_document_for_review(parent_doc, row) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow import (
		ParentTableBinding,
		_route_parent_for_review,
	)

	profile = _profile()
	binding = ParentTableBinding(
		parent_doctype=parent_doc.doctype,
		table_field=row.parentfield or "",
		child_doctype=row.doctype,
		profile_key=profile.key,
	)
	_route_parent_for_review(parent_doc, binding, profile, [row])


@frappe.whitelist()
def get_final_document_workflow_actions(
	parent_doctype: str,
	parent_name: str,
	child_row_name: str,
	child_table_field: str,
) -> list[dict[str, str]]:
	return []


@frappe.whitelist()
def apply_final_document_workflow_action(
	parent_doctype: str,
	parent_name: str,
	child_row_name: str,
	child_table_field: str,
	action: str,
) -> dict:
	frappe.throw(
		_("Use the parent document <b>Send for Review</b> or <b>Review Final Documents</b> buttons.")
	)
