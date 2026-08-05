"""Sales Invoice approval workflow."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cstr
from frappe.utils.user import get_users_with_role

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SALES_INVOICE_APPROVED_BY_FIELD,
	SALES_INVOICE_REJECTED_BY_FIELD,
	SALES_INVOICE_REJECTION_REASON_FIELD,
	SALES_INVOICE_SUBMITTABLE_STATES,
	SALES_INVOICE_WORKFLOW_STATE_APPROVED,
	SALES_INVOICE_WORKFLOW_STATE_DRAFT,
	SALES_INVOICE_WORKFLOW_STATE_PENDING,
	SALES_INVOICE_WORKFLOW_STATE_REJECTED,
)

REVIEW_ROLES = ("Accounts Manager", "Accounts User")


def validate_sales_invoice(doc, method=None) -> None:
	validate_sales_invoice_project_reference(doc)
	validate_sales_invoice_workflow(doc)


def validate_sales_invoice_workflow(doc) -> None:
	if not doc.meta.has_field("workflow_state"):
		return
	if doc.docstatus != 0:
		return
	if not doc.workflow_state:
		doc.workflow_state = SALES_INVOICE_WORKFLOW_STATE_DRAFT


def validate_sales_invoice_project_reference(doc) -> None:
	if not doc.meta.has_field("custom_project_name"):
		return

	project = (cstr(doc.get("project")) or "").strip()
	project_name = (cstr(doc.get("custom_project_name")) or "").strip()
	if not project and not project_name:
		frappe.throw(_("Please select a Project or enter a Project Name."))


def before_submit_sales_invoice(doc, method=None) -> None:
	"""Guard against submitting without approval (Approve sets workflow_state then submits)."""
	if not doc.meta.has_field("workflow_state"):
		return
	if (doc.workflow_state or "").strip() not in SALES_INVOICE_SUBMITTABLE_STATES:
		frappe.throw(
			_("Submit this Sales Invoice only after it has been approved."),
			title=_("Approval Required"),
		)


def on_update_sales_invoice_workflow(doc, method=None) -> None:
	if not doc.meta.has_field("workflow_state"):
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	prev = (before.workflow_state or "").strip()
	curr = (doc.workflow_state or "").strip()
	if curr == prev:
		return

	if curr == SALES_INVOICE_WORKFLOW_STATE_PENDING:
		_share_sales_invoice_with_reviewers(doc)
	elif curr == SALES_INVOICE_WORKFLOW_STATE_APPROVED:
		_stamp_sales_invoice_approval(doc)
	elif curr == SALES_INVOICE_WORKFLOW_STATE_REJECTED:
		_stamp_sales_invoice_rejection(doc)
	elif curr == SALES_INVOICE_WORKFLOW_STATE_DRAFT:
		_reset_sales_invoice_approval_stamps(doc)


def _share_sales_invoice_with_reviewers(doc) -> None:
	users = _reviewer_users()
	if not users:
		return

	for user in users:
		if user in {doc.owner, frappe.session.user}:
			continue
		frappe.share.add_docshare(
			doc.doctype,
			doc.name,
			user,
			read=1,
			write=0,
			notify=1,
		)


def _reviewer_users() -> set[str]:
	users: set[str] = set()
	for role in REVIEW_ROLES:
		users.update(get_users_with_role(role) or [])
	return {user for user in users if user and user != "Guest"}


def _stamp_sales_invoice_approval(doc) -> None:
	updates = {
		SALES_INVOICE_APPROVED_BY_FIELD: frappe.session.user,
		SALES_INVOICE_REJECTED_BY_FIELD: None,
		SALES_INVOICE_REJECTION_REASON_FIELD: None,
	}
	for fieldname, value in updates.items():
		if doc.meta.has_field(fieldname):
			doc.db_set(fieldname, value, update_modified=False)


def _stamp_sales_invoice_rejection(doc) -> None:
	reason = (cstr(doc.get(SALES_INVOICE_REJECTION_REASON_FIELD)) or "").strip() or None
	updates = {
		SALES_INVOICE_REJECTED_BY_FIELD: frappe.session.user,
		SALES_INVOICE_APPROVED_BY_FIELD: None,
		SALES_INVOICE_REJECTION_REASON_FIELD: reason,
	}
	for fieldname, value in updates.items():
		if doc.meta.has_field(fieldname):
			doc.db_set(fieldname, value, update_modified=False)


def _reset_sales_invoice_approval_stamps(doc) -> None:
	updates = {
		SALES_INVOICE_APPROVED_BY_FIELD: None,
		SALES_INVOICE_REJECTED_BY_FIELD: None,
		SALES_INVOICE_REJECTION_REASON_FIELD: None,
	}
	for fieldname, value in updates.items():
		if doc.meta.has_field(fieldname) and doc.get(fieldname):
			doc.db_set(fieldname, value, update_modified=False)
