# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	FUNDING_REQUEST_APPROVED_STATES,
	FUNDING_REQUEST_STATE_APPROVED,
	FUNDING_REQUEST_STATE_CANCELLED,
	FUNDING_REQUEST_STATE_FUNDED,
	FUNDING_REQUEST_STATE_PENDING,
	MR_FUNDING_WORKFLOW_STATE_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
	INACTIVE_FUNDING_STATES,
	_material_requests_on_active_funding_requests,
	funding_approval_is_recorded,
	funding_is_approved,
	funding_progress_state,
	get_material_request_item_summary,
	get_material_request_total,
	mr_row_funding_state,
	reduction_amount,
	released_mr_funding_state,
)


class FundingRequest(Document):
	def before_validate(self):
		self._drop_blank_material_request_rows()

	def validate(self):
		self._drop_blank_material_request_rows()
		self._validate_material_requests()
		self._apply_row_amounts()
		self.calculate_totals()
		self._validate_director_reductions()
		self._validate_funding_complete()
		self._stamp_director_approval()

	def on_update(self):
		self.sync_material_request_links()

	def on_submit(self):
		self.sync_material_request_links()

	def on_update_after_submit(self):
		self.calculate_totals()
		self.sync_material_request_links()

	def on_cancel(self):
		self.workflow_state = FUNDING_REQUEST_STATE_CANCELLED
		self.sync_material_request_links(release=True)

	def calculate_totals(self) -> None:
		self.total_requests = len(self.material_requests or [])
		self.total_requested = flt(sum(flt(row.requested_amount) for row in self.material_requests))
		self.total_funded = flt(sum(flt(row.funded_amount) for row in self.material_requests))
		if funding_approval_is_recorded(self.workflow_state):
			self.total_approved = flt(sum(flt(row.approved_amount) for row in self.material_requests))
			self.total_reduction = reduction_amount(self.total_requested, self.total_approved)
			self.outstanding = flt(self.total_approved) - flt(self.total_funded)
			return
		self.total_approved = 0
		self.total_reduction = 0
		self.outstanding = 0

	def _sync_funding_progress_state(self) -> None:
		"""Director Approved → Funding in Progress / Funded from actual payments only."""
		next_state = funding_progress_state(
			self.workflow_state, self.total_funded, self.total_approved
		)
		if next_state and next_state != self.workflow_state:
			self.workflow_state = next_state

	def _drop_blank_material_request_rows(self) -> None:
		for row in list(self.get("material_requests") or []):
			if not row.material_request:
				self.remove(row)

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
				["docstatus", "status"],
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

	def _apply_row_amounts(self) -> None:
		for row in self.material_requests:
			requested = get_material_request_total(row.material_request)
			row.requested_amount = requested
			if row.meta.has_field("item_summary"):
				row.item_summary = get_material_request_item_summary(row.material_request)
			if self.workflow_state in FUNDING_REQUEST_APPROVED_STATES:
				if row.approved_amount in (None, "") or flt(row.approved_amount) == 0:
					row.approved_amount = requested
				row.reduction_amount = reduction_amount(row.requested_amount, row.approved_amount)
			elif self.workflow_state == FUNDING_REQUEST_STATE_PENDING:
				if row.approved_amount in (None, ""):
					row.approved_amount = 0
				if flt(row.approved_amount) > 0:
					row.reduction_amount = reduction_amount(row.requested_amount, row.approved_amount)
				else:
					row.reduction_amount = 0
			else:
				row.approved_amount = 0
				row.reduction_amount = 0
			row.status = mr_row_funding_state(
				self.workflow_state, row.approved_amount, row.funded_amount
			)

	def _validate_director_reductions(self) -> None:
		for row in self.material_requests:
			if flt(row.approved_amount) < 0:
				frappe.throw(_("Row {0}: Approved Amount cannot be negative.").format(row.idx))
			if flt(row.approved_amount) - flt(row.requested_amount) > 0.005:
				frappe.throw(
					_(
						"Row {0}: Approved Amount cannot exceed the original Requested Amount {1}."
					).format(row.idx, frappe.bold(row.requested_amount))
				)
			if (
				self.workflow_state in (FUNDING_REQUEST_STATE_PENDING, FUNDING_REQUEST_STATE_APPROVED)
				and flt(row.approved_amount) > 0
				and flt(row.approved_amount) + 0.005 < flt(row.requested_amount)
				and not (row.reduction_reason or "").strip()
			):
				frappe.throw(
					_("Row {0}: Reduction Reason is required when approving less than requested.").format(
						row.idx
					)
				)

	def _validate_funding_complete(self) -> None:
		if self.workflow_state != FUNDING_REQUEST_STATE_FUNDED:
			return
		if flt(self.total_funded) <= 0:
			frappe.throw(
				_("Cannot mark funding complete when no actual funding transaction exists.")
			)

	def _stamp_director_approval(self) -> None:
		if self.workflow_state != FUNDING_REQUEST_STATE_APPROVED:
			return
		if not self.director:
			self.director = frappe.session.user
		if not self.approval_date:
			self.approval_date = nowdate()

	def sync_material_request_links(self, release: bool = False) -> None:
		if release or self.workflow_state in INACTIVE_FUNDING_STATES:
			self._release_material_requests()
			return
		for row in self.material_requests:
			if not row.material_request:
				continue
			values = {
				"custom_funding_request": self.name,
				MR_FUNDING_WORKFLOW_STATE_FIELD: mr_row_funding_state(
					self.workflow_state, row.approved_amount, row.funded_amount
				),
			}
			if funding_is_approved(self.workflow_state, self.docstatus):
				values["custom_approved_amount"] = flt(row.approved_amount)
			frappe.db.set_value("Material Request", row.material_request, values, update_modified=False)

	def _release_material_requests(self) -> None:
		for row in self.material_requests:
			if not row.material_request:
				continue
			current = frappe.db.get_value(
				"Material Request", row.material_request, "custom_funding_request"
			)
			if current and current != self.name:
				continue
			frappe.db.set_value(
				"Material Request",
				row.material_request,
				{
					"custom_funding_request": None,
					MR_FUNDING_WORKFLOW_STATE_FIELD: released_mr_funding_state(row.material_request),
					"custom_approved_amount": 0,
				},
				update_modified=False,
			)
