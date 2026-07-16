"""Generic child-table attachment approval workflow driven from the parent form.

Profiles declare attachment/status/approval field mappings. Parent bindings wire
each child table on Task, Project, Opportunity, etc. to a profile. Submitters use
parent-level Send for Review; approvers use a single Review dialog on the parent.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import frappe
from frappe import _
from frappe.utils import get_fullname, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	APPROVAL_STATUS_APPROVED,
	APPROVAL_STATUS_DRAFT,
	APPROVAL_STATUS_PENDING_REVIEW,
	APPROVAL_STATUS_REJECTED,
	APPROVAL_WORKFLOW_ACTION_APPROVE,
	APPROVAL_WORKFLOW_ACTION_REJECT,
	APPROVAL_WORKFLOW_ACTION_SEND,
	FINAL_DOCUMENT_NOTIFICATION,
	OPPORTUNITY_DOCUMENTS_FIELD,
	SHIPMENT_DOCUMENTS_FIELD,
	TASK_DOCUMENTS_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
	send_notification,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
	user_has_operations_department_access,
)

ApproverCheck = Callable[[str | None], bool]
ApproverUsersFn = Callable[[], list[str]]


@dataclass(frozen=True)
class AttachmentApprovalProfile:
	"""Field mapping and routing for one attachable document slot on a child row."""

	key: str
	attach_field: str
	status_field: str
	approved_by_field: str
	approved_on_field: str
	label: str
	label_field: str | None = None
	rejection_reason_field: str | None = None
	notification: str | None = None
	notification_audience: str = "Operations"
	sendable_states: tuple[str, ...] = (APPROVAL_STATUS_DRAFT, APPROVAL_STATUS_REJECTED, "")
	review_description_template: str = "{label}"
	can_review: ApproverCheck = user_has_operations_department_access
	approver_users: ApproverUsersFn | None = None


@dataclass(frozen=True)
class ParentTableBinding:
	parent_doctype: str
	table_field: str
	child_doctype: str
	profile_key: str
	send_button_label: str | None = None
	review_button_label: str | None = None


_PROFILES: dict[str, AttachmentApprovalProfile] = {}
_BINDINGS: list[ParentTableBinding] = []


def register_profile(profile: AttachmentApprovalProfile) -> None:
	_PROFILES[profile.key] = profile


def register_binding(binding: ParentTableBinding) -> None:
	_BINDINGS.append(binding)


def get_profile(profile_key: str) -> AttachmentApprovalProfile:
	profile = _PROFILES.get(profile_key)
	if not profile:
		frappe.throw(_("Unknown attachment approval profile: {0}").format(profile_key))
	return profile


def bindings_for_parent(parent_doctype: str) -> list[ParentTableBinding]:
	return [b for b in _BINDINGS if b.parent_doctype == parent_doctype]


def bindings_for_parent_table(parent_doctype: str, table_field: str) -> list[ParentTableBinding]:
	return [
		b
		for b in _BINDINGS
		if b.parent_doctype == parent_doctype and b.table_field == table_field
	]


def _row_has_profile_fields(row, profile: AttachmentApprovalProfile) -> bool:
	meta = row.meta if hasattr(row, "meta") else frappe.get_meta(row.doctype)
	return meta.has_field(profile.attach_field) and meta.has_field(profile.status_field)


def row_status(row, profile: AttachmentApprovalProfile) -> str:
	if not row or not _row_has_profile_fields(row, profile):
		return ""
	return (row.get(profile.status_field) or "").strip() or APPROVAL_STATUS_DRAFT


def row_has_attachment(row, profile: AttachmentApprovalProfile) -> bool:
	return bool((row.get(profile.attach_field) or "").strip())


def row_label(row, profile: AttachmentApprovalProfile) -> str:
	if profile.label_field and row.get(profile.label_field):
		return str(row.get(profile.label_field))
	return row.name or profile.label


def _normalized_status(value: str | None) -> str:
	return (value or "").strip() or APPROVAL_STATUS_DRAFT


def _operations_approver_users() -> list[str]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		configured_operations_roles,
	)

	users: set[str] = set()
	for role in configured_operations_roles():
		for user in frappe.get_all(
			"Has Role",
			filters={"role": role, "parenttype": "User"},
			pluck="parent",
		):
			if frappe.db.get_value("User", user, "enabled"):
				users.add(user)
	return sorted(users)


def _resolve_approver_users(profile: AttachmentApprovalProfile) -> list[str]:
	if profile.approver_users:
		return profile.approver_users()
	return _operations_approver_users()


def _set_row_field(row, fieldname: str, value) -> None:
	setattr(row, fieldname, value)


def _clear_rejection_reason(row, profile: AttachmentApprovalProfile) -> None:
	if profile.rejection_reason_field and row.meta.has_field(profile.rejection_reason_field):
		_set_row_field(row, profile.rejection_reason_field, None)


def _set_rejection_reason(row, profile: AttachmentApprovalProfile, reason: str | None) -> None:
	if profile.rejection_reason_field and row.meta.has_field(profile.rejection_reason_field):
		_set_row_field(row, profile.rejection_reason_field, (reason or "").strip() or None)


def _apply_approval_metadata(row, profile: AttachmentApprovalProfile, *, approved: bool) -> None:
	if approved:
		if row.meta.has_field(profile.approved_by_field):
			_set_row_field(row, profile.approved_by_field, frappe.session.user)
		if row.meta.has_field(profile.approved_on_field):
			_set_row_field(row, profile.approved_on_field, now_datetime())
		_clear_rejection_reason(row, profile)
		return
	if row.meta.has_field(profile.approved_by_field):
		_set_row_field(row, profile.approved_by_field, None)
	if row.meta.has_field(profile.approved_on_field):
		_set_row_field(row, profile.approved_on_field, None)


def _reset_workflow(row, profile: AttachmentApprovalProfile) -> None:
	if not _row_has_profile_fields(row, profile):
		return
	_set_row_field(row, profile.status_field, APPROVAL_STATUS_DRAFT)
	_apply_approval_metadata(row, profile, approved=False)
	_clear_rejection_reason(row, profile)


def sync_workflow_on_attachment_change(
	row,
	profile: AttachmentApprovalProfile,
	prev_row=None,
) -> None:
	if not _row_has_profile_fields(row, profile):
		return

	current = (row.get(profile.attach_field) or "").strip()
	previous = (prev_row.get(profile.attach_field) or "").strip() if prev_row else ""

	if current == previous:
		return

	if not current:
		_reset_workflow(row, profile)
		return

	status = row_status(row, profile)
	if status in (
		APPROVAL_STATUS_PENDING_REVIEW,
		APPROVAL_STATUS_APPROVED,
		APPROVAL_STATUS_REJECTED,
	):
		_reset_workflow(row, profile)
	elif not row.get(profile.status_field):
		_set_row_field(row, profile.status_field, APPROVAL_STATUS_DRAFT)


def ensure_status_defaults(rows: Iterable, profile: AttachmentApprovalProfile) -> None:
	for row in rows or []:
		if not _row_has_profile_fields(row, profile):
			continue
		if not row.get(profile.status_field):
			_set_row_field(row, profile.status_field, APPROVAL_STATUS_DRAFT)


def validate_workflow_on_parent_save(
	parent_doc,
	table_field: str,
	profile: AttachmentApprovalProfile,
) -> None:
	if frappe.flags.get("cgm_applying_attachment_approval"):
		return
	if not parent_doc.meta.has_field(table_field):
		return

	prev = parent_doc.get_doc_before_save()
	if not prev:
		ensure_status_defaults(parent_doc.get(table_field), profile)
		return

	prev_by_name = {row.name: row for row in prev.get(table_field) or [] if row.name}
	for row in parent_doc.get(table_field) or []:
		prev_row = prev_by_name.get(row.name)
		if not prev_row or not _row_has_profile_fields(row, profile):
			continue
		current_status = _normalized_status(row.get(profile.status_field))
		previous_status = _normalized_status(prev_row.get(profile.status_field))
		if current_status == previous_status:
			continue
		current_file = (row.get(profile.attach_field) or "").strip()
		previous_file = (prev_row.get(profile.attach_field) or "").strip()
		if current_file != previous_file:
			continue
		if frappe.flags.get("cgm_syncing_shipment_documents"):
			continue
		frappe.throw(
			_(
				"Change <b>{0}</b> using the parent document <b>Send for Review</b> or "
				"<b>Review Documents</b> actions, not by editing the field."
			).format(profile.label)
		)


def stamp_child_table_approval_workflows(doc, table_field: str) -> None:
	"""Sync attachment-driven workflow state for every profile bound to this table."""
	bindings = bindings_for_parent_table(doc.doctype, table_field)
	if not bindings:
		return

	prev = doc.get_doc_before_save()
	prev_by_name = {}
	if prev and prev.meta.has_field(table_field):
		prev_by_name = {row.name: row for row in prev.get(table_field) or [] if row.name}

	seen_profiles: set[str] = set()
	for binding in bindings:
		if binding.profile_key in seen_profiles:
			continue
		seen_profiles.add(binding.profile_key)
		profile = get_profile(binding.profile_key)
		for row in doc.get(table_field) or []:
			sync_workflow_on_attachment_change(
				row, profile, prev_by_name.get(row.name)
			)
		ensure_status_defaults(doc.get(table_field), profile)
		validate_workflow_on_parent_save(doc, table_field, profile)


def _find_child_row(parent_doc, table_field: str, row_name: str):
	for row in parent_doc.get(table_field) or []:
		if row.name == row_name:
			return row
	frappe.throw(_("Child row not found."))


def _serialize_row(
	row,
	binding: ParentTableBinding,
	profile: AttachmentApprovalProfile,
) -> dict[str, Any]:
	approved_by = row.get(profile.approved_by_field)
	return {
		"profile_key": profile.key,
		"table_field": binding.table_field,
		"child_doctype": binding.child_doctype,
		"row_name": row.name,
		"label": row_label(row, profile),
		"attachment": row.get(profile.attach_field),
		"status": row_status(row, profile),
		"approved_by": approved_by,
		"approved_by_name": get_fullname(approved_by) if approved_by else None,
		"approved_on": row.get(profile.approved_on_field),
		"rejection_reason": (
			row.get(profile.rejection_reason_field)
			if profile.rejection_reason_field and row.meta.has_field(profile.rejection_reason_field)
			else None
		),
		"profile_label": profile.label,
	}


def get_sendable_rows(
	parent_doc,
	binding: ParentTableBinding,
	profile: AttachmentApprovalProfile,
) -> list:
	rows = []
	for row in parent_doc.get(binding.table_field) or []:
		if row.doctype != binding.child_doctype:
			continue
		if not _row_has_profile_fields(row, profile):
			continue
		if not row_has_attachment(row, profile):
			continue
		if row_status(row, profile) in profile.sendable_states:
			rows.append(row)
	return rows


def get_pending_review_rows(
	parent_doc,
	binding: ParentTableBinding,
	profile: AttachmentApprovalProfile,
) -> list:
	rows = []
	for row in parent_doc.get(binding.table_field) or []:
		if row.doctype != binding.child_doctype:
			continue
		if not _row_has_profile_fields(row, profile):
			continue
		if row_status(row, profile) == APPROVAL_STATUS_PENDING_REVIEW:
			rows.append(row)
	return rows


def _route_parent_for_review(
	parent_doc,
	binding: ParentTableBinding,
	profile: AttachmentApprovalProfile,
	rows: list,
) -> None:
	from frappe.desk.form.assign_to import add as assign_to

	users = _resolve_approver_users(profile)
	if not users:
		frappe.throw(
			_(
				"Configure <b>Operations roles</b> on {0} before sending documents for review."
			).format(frappe.utils.get_link_to_form("CGM Shipping Settings", "CGM Shipping Settings"))
		)

	labels = [row_label(row, profile) for row in rows]
	if len(labels) == 1:
		description = profile.review_description_template.format(label=labels[0])
	else:
		description = _("{0} review: {1}").format(
			profile.label,
			", ".join(labels[:5]) + ("…" if len(labels) > 5 else ""),
		)

	assign_to(
		{
			"doctype": parent_doc.doctype,
			"name": parent_doc.name,
			"assign_to": users,
			"description": description,
		}
	)

	if profile.notification and frappe.db.exists("Notification", profile.notification):
		parent_doc.cgm_attachment_review_label = description
		send_notification(profile.notification, parent_doc, audience=profile.notification_audience)


def _apply_transition(
	parent_doc,
	binding: ParentTableBinding,
	profile: AttachmentApprovalProfile,
	row,
	action: str,
	*,
	rejection_reason: str | None = None,
) -> None:
	if not row_has_attachment(row, profile):
		frappe.throw(_("Attach a file before using workflow actions for {0}.").format(profile.label))

	current_status = row_status(row, profile)
	if action == APPROVAL_WORKFLOW_ACTION_SEND:
		if current_status not in profile.sendable_states:
			frappe.throw(
				_("Cannot send <b>{0}</b> for review when status is <b>{1}</b>.").format(
					row_label(row, profile), current_status
				)
			)
		if not frappe.has_permission(parent_doc.doctype, "write", doc=parent_doc):
			frappe.throw(_("You do not have permission to send documents for review."))
		_set_row_field(row, profile.status_field, APPROVAL_STATUS_PENDING_REVIEW)
		_apply_approval_metadata(row, profile, approved=False)
		_clear_rejection_reason(row, profile)
	elif action == APPROVAL_WORKFLOW_ACTION_APPROVE:
		if current_status != APPROVAL_STATUS_PENDING_REVIEW:
			frappe.throw(
				_("Cannot approve <b>{0}</b> when status is <b>{1}</b>.").format(
					row_label(row, profile), current_status
				)
			)
		if not profile.can_review():
			frappe.throw(_("You are not authorized to approve {0}.").format(profile.label))
		_set_row_field(row, profile.status_field, APPROVAL_STATUS_APPROVED)
		_apply_approval_metadata(row, profile, approved=True)
	elif action == APPROVAL_WORKFLOW_ACTION_REJECT:
		if current_status != APPROVAL_STATUS_PENDING_REVIEW:
			frappe.throw(
				_("Cannot reject <b>{0}</b> when status is <b>{1}</b>.").format(
					row_label(row, profile), current_status
				)
			)
		if not profile.can_review():
			frappe.throw(_("You are not authorized to reject {0}.").format(profile.label))
		_set_row_field(row, profile.status_field, APPROVAL_STATUS_REJECTED)
		_apply_approval_metadata(row, profile, approved=False)
		_set_rejection_reason(row, profile, rejection_reason)
	else:
		frappe.throw(_("Unknown workflow action: {0}").format(action))


@frappe.whitelist()
def get_parent_attachment_approval_state(parent_doctype: str, parent_name: str) -> dict[str, Any]:
	parent = frappe.get_doc(parent_doctype, parent_name)
	frappe.has_permission(parent_doctype, ptype="read", doc=parent, throw=True)

	can_write = frappe.has_permission(parent_doctype, "write", doc=parent)
	can_review = user_has_operations_department_access()
	sendable_count = 0
	pending_count = 0
	profiles: list[dict[str, Any]] = []

	for binding in bindings_for_parent(parent_doctype):
		profile = get_profile(binding.profile_key)
		if not parent.meta.has_field(binding.table_field):
			continue
		sendable = get_sendable_rows(parent, binding, profile)
		pending = get_pending_review_rows(parent, binding, profile)
		sendable_count += len(sendable)
		pending_count += len(pending)
		if sendable or pending:
			profiles.append(
				{
					"profile_key": profile.key,
					"profile_label": profile.label,
					"table_field": binding.table_field,
					"send_button_label": binding.send_button_label or _("Send {0} for Review").format(profile.label),
					"review_button_label": binding.review_button_label
					or _("Review {0}").format(profile.label),
					"sendable_count": len(sendable),
					"pending_count": len(pending),
				}
			)

	return {
		"can_send": bool(can_write and sendable_count),
		"can_review": bool(can_review and pending_count),
		"sendable_count": sendable_count,
		"pending_count": pending_count,
		"profiles": profiles,
	}


@frappe.whitelist()
def get_sendable_attachment_rows(parent_doctype: str, parent_name: str) -> list[dict[str, Any]]:
	parent = frappe.get_doc(parent_doctype, parent_name)
	frappe.has_permission(parent_doctype, ptype="write", doc=parent, throw=True)

	rows: list[dict[str, Any]] = []
	for binding in bindings_for_parent(parent_doctype):
		profile = get_profile(binding.profile_key)
		if not parent.meta.has_field(binding.table_field):
			continue
		for row in get_sendable_rows(parent, binding, profile):
			payload = _serialize_row(row, binding, profile)
			payload["selected"] = 1
			rows.append(payload)
	return rows


@frappe.whitelist()
def send_attachments_for_review(
	parent_doctype: str,
	parent_name: str,
	selections_json: str,
) -> dict[str, Any]:
	parent = frappe.get_doc(parent_doctype, parent_name)
	frappe.has_permission(parent_doctype, ptype="write", doc=parent, throw=True)

	selections = json.loads(selections_json or "[]")
	if not selections:
		frappe.throw(_("Select at least one document to send for review."))

	grouped: dict[str, list[tuple[ParentTableBinding, AttachmentApprovalProfile, Any]]] = {}
	for item in selections:
		profile_key = item.get("profile_key")
		row_name = item.get("row_name")
		table_field = item.get("table_field")
		if not profile_key or not row_name or not table_field:
			continue
		binding = next(
			(
				b
				for b in bindings_for_parent(parent_doctype)
				if b.profile_key == profile_key and b.table_field == table_field
			),
			None,
		)
		if not binding:
			continue
		profile = get_profile(profile_key)
		row = _find_child_row(parent, table_field, row_name)
		grouped.setdefault(profile_key, []).append((binding, profile, row))

	if not grouped:
		frappe.throw(_("No valid documents were selected."))

	frappe.flags.cgm_applying_attachment_approval = True
	try:
		for profile_key, items in grouped.items():
			profile = get_profile(profile_key)
			rows = [row for _binding, _profile, row in items]
			binding = items[0][0]
			for _binding, _profile, row in items:
				_apply_transition(parent, _binding, profile, row, APPROVAL_WORKFLOW_ACTION_SEND)
			_route_parent_for_review(parent, binding, profile, rows)
		parent.save()
	finally:
		frappe.flags.cgm_applying_attachment_approval = False

	return get_parent_attachment_approval_state(parent_doctype, parent_name)


@frappe.whitelist()
def get_pending_attachment_review_rows(
	parent_doctype: str,
	parent_name: str,
) -> list[dict[str, Any]]:
	parent = frappe.get_doc(parent_doctype, parent_name)
	frappe.has_permission(parent_doctype, ptype="read", doc=parent, throw=True)
	if not user_has_operations_department_access():
		frappe.throw(_("You are not authorized to review these documents."))

	rows: list[dict[str, Any]] = []
	for binding in bindings_for_parent(parent_doctype):
		profile = get_profile(binding.profile_key)
		if not parent.meta.has_field(binding.table_field):
			continue
		for row in get_pending_review_rows(parent, binding, profile):
			payload = _serialize_row(row, binding, profile)
			rows.append(payload)
	return rows


@frappe.whitelist()
def apply_attachment_review_decisions(
	parent_doctype: str,
	parent_name: str,
	decisions_json: str,
) -> dict[str, Any]:
	parent = frappe.get_doc(parent_doctype, parent_name)
	frappe.has_permission(parent_doctype, ptype="write", doc=parent, throw=True)
	if not user_has_operations_department_access():
		frappe.throw(_("You are not authorized to review these documents."))

	decisions = json.loads(decisions_json or "[]")
	if not decisions:
		frappe.throw(_("Select approve or reject for at least one document."))

	frappe.flags.cgm_applying_attachment_approval = True
	try:
		for item in decisions:
			action = item.get("action")
			if action not in (APPROVAL_WORKFLOW_ACTION_APPROVE, APPROVAL_WORKFLOW_ACTION_REJECT):
				continue
			profile_key = item.get("profile_key")
			row_name = item.get("row_name")
			table_field = item.get("table_field")
			if not profile_key or not row_name or not table_field:
				continue
			binding = next(
				(
					b
					for b in bindings_for_parent(parent_doctype)
					if b.profile_key == profile_key and b.table_field == table_field
				),
				None,
			)
			if not binding:
				continue
			profile = get_profile(profile_key)
			row = _find_child_row(parent, table_field, row_name)
			_apply_transition(
				parent,
				binding,
				profile,
				row,
				action,
				rejection_reason=item.get("rejection_reason"),
			)
		parent.save()
	finally:
		frappe.flags.cgm_applying_attachment_approval = False

	return get_parent_attachment_approval_state(parent_doctype, parent_name)


def _register_default_profiles() -> None:
	register_profile(
		AttachmentApprovalProfile(
			key="shipment_final_document",
			attach_field="final_attachment",
			status_field="final_document_status",
			approved_by_field="final_document_approved_by",
			approved_on_field="final_document_approved_on",
			label=_("Final Document"),
			label_field="document_type",
			rejection_reason_field="reason_for_rejection",
			notification=FINAL_DOCUMENT_NOTIFICATION,
			review_description_template=_("Final document review: {label}"),
		)
	)

	# Ready for future child-table approval fields on Permit Register.
	register_profile(
		AttachmentApprovalProfile(
			key="permit_payment_invoice",
			attach_field="payment_invoice",
			status_field="payment_invoice_status",
			approved_by_field="payment_invoice_approved_by",
			approved_on_field="payment_invoice_approved_on",
			label=_("Permit Invoice"),
			label_field="permit_type",
			review_description_template=_("Permit invoice review: {label}"),
		)
	)
	register_profile(
		AttachmentApprovalProfile(
			key="permit_certificate",
			attach_field="permit_document",
			status_field="permit_document_status",
			approved_by_field="permit_document_approved_by",
			approved_on_field="permit_document_approved_on",
			label=_("Permit Certificate"),
			label_field="permit_type",
			review_description_template=_("Permit certificate review: {label}"),
		)
	)


def _register_default_bindings() -> None:
	for parent_doctype, table_field, send_label, review_label in (
		("Task", TASK_DOCUMENTS_FIELD, _("Send Final Documents for Review"), _("Review Final Documents")),
		("Project", SHIPMENT_DOCUMENTS_FIELD, _("Send Final Documents for Review"), _("Review Final Documents")),
		(
			"Opportunity",
			OPPORTUNITY_DOCUMENTS_FIELD,
			_("Send Final Documents for Review"),
			_("Review Final Documents"),
		),
	):
		register_binding(
			ParentTableBinding(
				parent_doctype=parent_doctype,
				table_field=table_field,
				child_doctype="Shipment Document",
				profile_key="shipment_final_document",
				send_button_label=send_label,
				review_button_label=review_label,
			)
		)


_register_default_profiles()
_register_default_bindings()
