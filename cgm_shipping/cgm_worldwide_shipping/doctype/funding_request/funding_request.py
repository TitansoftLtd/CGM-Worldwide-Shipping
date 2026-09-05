# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, nowdate

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	FR_ROW_DECISION_APPROVED,
	FR_ROW_DECISION_PENDING,
	FR_ROW_DECISION_REJECTED,
	MR_WORKFLOW_STATE_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
	FUNDING_MATERIAL_REQUEST_TYPES,
	_material_requests_on_active_funding_requests,
	apply_batch_approve_to_pending_rows,
	funding_batch_is_partially_approved,
	funding_approval_is_recorded,
	funding_is_approved,
	funding_is_pending,
	funding_progress_state,
	get_material_request_item_summary,
	get_material_request_total,
	get_material_request_requester_name,
	mr_row_workflow_state,
	mr_workflow_state_from_funding_request,
	released_mr_workflow_state,
	variance_amount,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
	get_funding_workflow_map,
)

MATERIAL_REQUEST_LINK_PLACEHOLDER = "Material Request"
AMOUNT_TOLERANCE = 0.005


def is_valid_funding_material_request_link(material_request: str | None) -> bool:
	mr = (material_request or "").strip()
	if not mr:
		return False
	return mr != MATERIAL_REQUEST_LINK_PLACEHOLDER


class FundingRequest(Document):
	def before_validate(self):
		self._drop_invalid_material_request_rows()

	def validate(self):
		self._validate_material_requests()
		self._normalize_row_decisions()
		self._apply_batch_approve_to_pending_rows()
		self._apply_row_amounts()
		self._validate_approval_decisions()
		self._ensure_submitted_by()
		self.calculate_totals()
		self._validate_row_approvals()
		self._validate_funding_complete()
		self._stamp_approval()

	def on_update(self):
		self._apply_partial_approval_state()
		self.sync_material_request_links()

	def on_submit(self):
		self.sync_material_request_links()

	def on_update_after_submit(self):
		self._apply_partial_approval_state()
		self.calculate_totals()
		self.sync_material_request_links()

	def on_cancel(self):
		cancel_state = get_funding_workflow_map().cancel_state
		if cancel_state:
			self.workflow_state = cancel_state
		self.sync_material_request_links(release=True)

	def calculate_totals(self) -> None:
		rows = self._valid_material_request_rows()
		approved_rows = self._approved_rows(rows)
		self.total_requests = len(rows)
		self.total_requested = flt(sum(flt(row.requested_amount) for row in rows))
		self.total_funded = flt(sum(flt(row.funded_amount) for row in approved_rows))
		if funding_approval_is_recorded(self.workflow_state):
			self.total_approved = flt(sum(flt(row.approved_amount) for row in approved_rows))
			self.total_variance = flt(
				sum(variance_amount(row.requested_amount, row.approved_amount) for row in approved_rows)
			)
			self.outstanding = flt(self.total_approved) - flt(self.total_funded)
			return
		self.total_approved = 0
		if self.meta.has_field("total_variance"):
			self.total_variance = 0
		self.outstanding = 0

	def _sync_funding_progress_state(self) -> None:
		next_state = funding_progress_state(
			self.workflow_state, self.total_funded, self.total_approved
		)
		if next_state and next_state != self.workflow_state:
			self.workflow_state = next_state

	def _valid_material_request_rows(self):
		return [
			row
			for row in (self.material_requests or [])
			if is_valid_funding_material_request_link(row.material_request)
		]

	@staticmethod
	def _approved_rows(rows):
		return [row for row in rows if row.get("decision") == FR_ROW_DECISION_APPROVED]

	def _drop_invalid_material_request_rows(self) -> None:
		for row in list(self.get("material_requests") or []):
			if not is_valid_funding_material_request_link(row.material_request):
				self.remove(row)

	def _normalize_row_decisions(self) -> None:
		for row in self.material_requests:
			if not row.get("decision"):
				row.decision = FR_ROW_DECISION_PENDING
			if row.decision == FR_ROW_DECISION_REJECTED:
				row.approved_amount = 0
			elif row.decision == FR_ROW_DECISION_APPROVED and flt(row.approved_amount) == 0:
				row.approved_amount = flt(row.requested_amount)

	def _apply_batch_approve_to_pending_rows(self) -> None:
		"""Header Approve approves remaining Pending rows (Reject rows stay rejected)."""
		if not get_funding_workflow_map().is_approve_next(self.workflow_state):
			return
		apply_batch_approve_to_pending_rows(self._valid_material_request_rows())

	def _validate_approval_decisions(self) -> None:
		"""Validate row decisions when the Approve workflow action is applied."""
		if not get_funding_workflow_map().is_approve_next(self.workflow_state):
			return
		rows = self._valid_material_request_rows()
		approved = [row for row in rows if row.decision == FR_ROW_DECISION_APPROVED]
		if not approved:
			frappe.throw(
				_(
					"All Material Requests are rejected. Use Reject on the Funding Request instead of Approve."
				)
			)

	def _apply_partial_approval_state(self) -> None:
		"""After Approve, move to Partially Approved when the batch is not fully approved.

		Partially Approved is never chosen from Actions. It applies when some Material
		Requests were rejected or an approved amount is below the requested amount.
		"""
		wf = get_funding_workflow_map()
		if not wf.is_approve_next(self.workflow_state) or not wf.partial_state:
			return
		rows = self._valid_material_request_rows()
		if not funding_batch_is_partially_approved(rows, tolerance=AMOUNT_TOLERANCE):
			return
		frappe.db.set_value(
			"Funding Request",
			self.name,
			"workflow_state",
			wf.partial_state,
			update_modified=False,
		)
		self.workflow_state = wf.partial_state
		if not self.approved_by:
			self.approved_by = frappe.session.user
		if not self.approval_date:
			self.approval_date = nowdate()

	def _ensure_submitted_by(self) -> None:
		if not funding_is_pending(self.workflow_state):
			return
		previous = self.get_doc_before_save() if not self.is_new() else None
		previous_state = previous.workflow_state if previous else None
		if not self.submitted_by or not funding_is_pending(previous_state):
			self.submitted_by = frappe.session.user
		if not self.submitted_by:
			frappe.throw(_("Submitted By is required when sending a Funding Request for approval."))

	def _validate_material_requests(self) -> None:
		if not self.material_requests:
			frappe.throw(_("Select at least one Material Request."))
		seen = set()
		blocked = set(_material_requests_on_active_funding_requests(exclude_parent=self.name))
		for row in self.material_requests:
			if not row.material_request:
				frappe.throw(_("Row {0}: Material Request is required.").format(row.idx))
			if row.material_request in seen:
				frappe.throw(
					_("Material Request {0} is included more than once.").format(
						frappe.bold(row.material_request)
					)
				)
			seen.add(row.material_request)
			if row.material_request in blocked:
				frappe.throw(
					_("Material Request {0} is already on another active Funding Request.").format(
						frappe.bold(row.material_request)
					)
				)
			mr = frappe.db.get_value(
				"Material Request",
				row.material_request,
				["docstatus", "status", "material_request_type"],
				as_dict=True,
			)
			if not mr or mr.docstatus != 1:
				frappe.throw(
					_("Material Request {0} must be submitted before it can be funded.").format(
						frappe.bold(row.material_request)
					)
				)
			if mr.status == "Stopped":
				frappe.throw(
					_("Material Request {0} is Stopped.").format(frappe.bold(row.material_request))
				)
			if (
				cint(self.docstatus) == 0
				and mr.material_request_type not in FUNDING_MATERIAL_REQUEST_TYPES
			):
				frappe.throw(
					_(
						"Funding Request is only for Purchase and Operational Expense. "
						"Material Request {0} is {1}."
					).format(
						frappe.bold(row.material_request),
						frappe.bold(mr.material_request_type or _("another type")),
					)
				)

	def _apply_row_amounts(self) -> None:
		for row in self.material_requests:
			requested = get_material_request_total(row.material_request)
			row.requested_amount = requested
			if row.meta.has_field("item_summary"):
				row.item_summary = get_material_request_item_summary(row.material_request)
			if row.meta.has_field("employee_name"):
				row.employee_name = get_material_request_requester_name(row.material_request)
			if funding_approval_is_recorded(self.workflow_state):
				if row.decision == FR_ROW_DECISION_APPROVED:
					if row.approved_amount in (None, "") or flt(row.approved_amount) == 0:
						row.approved_amount = requested
				elif row.decision == FR_ROW_DECISION_REJECTED:
					row.approved_amount = 0
			elif funding_is_pending(self.workflow_state):
				if row.decision == FR_ROW_DECISION_APPROVED and flt(row.approved_amount) == 0:
					row.approved_amount = requested
				if row.decision == FR_ROW_DECISION_REJECTED:
					row.approved_amount = 0
			else:
				row.approved_amount = 0
			if row.meta.has_field("variance"):
				row.variance = variance_amount(row.requested_amount, row.approved_amount)
			row.status = self._row_status_label(row)

	def _row_status_label(self, row) -> str:
		if row.decision == FR_ROW_DECISION_REJECTED:
			rejected = next(iter(get_funding_workflow_map().reject_next_states), "Rejected")
			return mr_workflow_state_from_funding_request(rejected)
		if row.decision == FR_ROW_DECISION_APPROVED and funding_approval_is_recorded(self.workflow_state):
			return mr_row_workflow_state(
				self.workflow_state, row.approved_amount, row.funded_amount
			)
		if funding_is_pending(self.workflow_state):
			return mr_workflow_state_from_funding_request(self.workflow_state)
		return row.decision or FR_ROW_DECISION_PENDING

	def _validate_row_approvals(self) -> None:
		wf = get_funding_workflow_map()
		if not (
			wf.is_pending(self.workflow_state)
			or wf.is_approve_next(self.workflow_state)
			or wf.is_partial(self.workflow_state)
		):
			return
		for row in self.material_requests:
			if row.decision == FR_ROW_DECISION_REJECTED:
				if not (row.rejection_reason or "").strip():
					frappe.throw(
						_("Row {0}: Rejection Reason is required for rejected Material Requests.").format(
							row.idx
						)
					)
				continue
			if row.decision != FR_ROW_DECISION_APPROVED:
				continue
			if flt(row.approved_amount) < 0:
				frappe.throw(_("Row {0}: Approved Amount cannot be negative.").format(row.idx))
			variance = variance_amount(row.requested_amount, row.approved_amount)
			if abs(variance) > AMOUNT_TOLERANCE and not (row.adjustment_reason or "").strip():
				if variance < 0:
					label = _("reduction")
				else:
					label = _("increase")
				frappe.throw(
					_("Row {0}: Adjustment Reason is required for the approved amount {1}.").format(
						row.idx, label
					)
				)

	def _validate_funding_complete(self) -> None:
		if not get_funding_workflow_map().is_completed(self.workflow_state):
			return
		if flt(self.total_funded) <= 0:
			frappe.throw(
				_("Cannot mark disbursement complete when no payment has been recorded.")
			)

	def _stamp_approval(self) -> None:
		if not get_funding_workflow_map().is_approval_stamp_state(self.workflow_state):
			return
		if not self.approved_by:
			self.approved_by = frappe.session.user
		if not self.approval_date:
			self.approval_date = nowdate()

	def sync_material_request_links(self, release: bool = False) -> None:
		if release or get_funding_workflow_map().is_terminal(self.workflow_state):
			self._release_material_requests()
			return
		for row in self.material_requests:
			if not row.material_request:
				continue
			if row.decision == FR_ROW_DECISION_REJECTED and funding_approval_is_recorded(
				self.workflow_state
			):
				self._release_single_material_request(row.material_request, rejected=True)
				continue
			values = {
				"custom_funding_request": self.name,
				MR_WORKFLOW_STATE_FIELD: self._material_request_workflow_state(row),
			}
			if funding_is_approved(self.workflow_state, self.docstatus) and row.decision == FR_ROW_DECISION_APPROVED:
				values["custom_approved_amount"] = flt(row.approved_amount)
			frappe.db.set_value("Material Request", row.material_request, values, update_modified=False)

	def _material_request_workflow_state(self, row) -> str:
		if row.decision == FR_ROW_DECISION_REJECTED:
			rejected = next(iter(get_funding_workflow_map().reject_next_states), "Rejected")
			return mr_workflow_state_from_funding_request(rejected)
		return mr_row_workflow_state(self.workflow_state, row.approved_amount, row.funded_amount)

	def _release_material_requests(self) -> None:
		for row in self.material_requests:
			if not row.material_request:
				continue
			self._release_single_material_request(row.material_request)

	def _release_single_material_request(self, material_request: str, *, rejected: bool = False) -> None:
		current = frappe.db.get_value("Material Request", material_request, "custom_funding_request")
		if current and current != self.name:
			return
		if rejected or get_funding_workflow_map().is_rejected(self.workflow_state):
			rejected_state = next(iter(get_funding_workflow_map().reject_next_states), "Rejected")
			mr_state = mr_workflow_state_from_funding_request(rejected_state)
		else:
			mr_state = released_mr_workflow_state(material_request)
		frappe.db.set_value(
			"Material Request",
			material_request,
			{
				"custom_funding_request": None,
				MR_WORKFLOW_STATE_FIELD: mr_state,
				"custom_approved_amount": 0,
			},
			update_modified=False,
		)
