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
from cgm_shipping.cgm_worldwide_shipping.customizations.dialogs import blocked_dialog
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
from cgm_shipping.cgm_worldwide_shipping.customizations.multicurrency import (
	company_currency,
	material_request_currency_totals,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
	another_approver_exists,
	funding_approver_role,
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
		self._block_self_approval()
		self._stamp_approval()
		self._set_pending_step()

	def _set_pending_step(self) -> None:
		"""Keep the pending step in step with the rows on every save."""
		if not self.meta.has_field("pending_step"):
			return
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import funding_pending_step

		self.pending_step = funding_pending_step(self)

	def on_update(self):
		self._apply_partial_approval_state()
		self.sync_material_request_links()

	def on_submit(self):
		self.sync_material_request_links()
		self._take_up_existing_orders()

	def _take_up_existing_orders(self) -> None:
		"""On approval, adopt Purchase Orders raised before this request existed."""
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			adopt_open_purchase_orders,
			funding_is_approved,
			sync_funding_request_paid_amounts,
		)

		if not funding_is_approved(self.workflow_state, self.docstatus):
			return
		if not adopt_open_purchase_orders(self):
			return
		# An order under way moves the request on; pick the new state up here so
		# the form does not show Approved over a request that is already in progress.
		sync_funding_request_paid_amounts(self.name)
		self.reload()

	def on_update_after_submit(self):
		self._apply_partial_approval_state()
		self.calculate_totals()
		self.sync_material_request_links()
		# Last: it posts entries that re-save this request from a fresh copy.
		self._disburse_on_workflow_action()

	def _disburse_on_workflow_action(self):
		"""The Disburse workflow action is the payment.

		Moving the request into its Disbursed state by a workflow action posts the
		Journal Entries. If they cannot be posted the error stops the action, so
		the state never says Disbursed over an unpaid request.

		Payments recorded any other way (an entry submitted by hand, a Purchase
		Order paid) reach Disbursed through `sync_funding_request_paid_amounts`,
		which writes the state without saving and so does not come through here.
		"""
		prev = self.get_doc_before_save()
		if not prev or prev.workflow_state == self.workflow_state:
			return
		if not get_funding_workflow_map().is_disbursed(self.workflow_state):
			return
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			disburse_on_workflow_action,
		)

		disburse_on_workflow_action(self.name)
		# The entries updated the rows and the state on a fresh copy.
		self.reload()

	def on_trash(self):
		"""Hand the Material Requests back before this record disappears.

		on_update claims them on every save, including in draft: it stamps
		custom_funding_request and moves the Material Request's workflow state out
		of Unfunded/Submitted. Only on_cancel and a terminal state ever released
		them, so deleting a draft left the stamps behind - and because
		get_unfunded_material_requests filters on that workflow state, a stranded
		request never appeared in "Get Material Requests" again. There was no way
		to fund it short of editing the record by hand.
		"""
		self.sync_material_request_links(release=True)

	def before_cancel(self):
		"""Take the payment documents with it. Before Frappe's link check, which
		would otherwise refuse the cancel because of the very entries this removes."""
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			cancel_funding_payment_documents,
			paid_amount_for_material_request,
		)

		cancel_funding_payment_documents(self)
		# Nothing is paid any more; the cancelled request should say so.
		for row in self.material_requests:
			if not row.material_request:
				continue
			paid, paid_base = paid_amount_for_material_request(
				self.name, row.material_request, row.get("currency")
			)
			row.funded_amount = paid
			if row.meta.has_field("base_funded_amount"):
				row.base_funded_amount = paid_base
		self.calculate_totals()
		if self.meta.has_field("pending_step"):
			self.pending_step = ""

	def on_cancel(self):
		cancel_state = get_funding_workflow_map().cancel_state
		if cancel_state:
			self.workflow_state = cancel_state
		self.sync_material_request_links(release=True)

	def calculate_totals(self) -> None:
		rows = self._valid_material_request_rows()
		approved_rows = self._approved_rows(rows)
		self.total_requests = len(rows)
		self.total_requested = self._base_sum(rows, "requested_amount")
		self.total_funded = self._base_sum(approved_rows, "funded_amount")
		if funding_approval_is_recorded(self.workflow_state):
			self.total_approved = self._base_sum(approved_rows, "approved_amount")
			self.total_variance = flt(self.total_approved) - flt(self.total_requested_approved_rows(approved_rows))
			# What is still to pay, row by row, each at its own rate. Not approved
			# minus funded: those two totals are converted at different rates (the
			# approval's and the payment's), so their difference is an exchange
			# difference, and a fully paid USD row showed as a few shillings owed.
			self.outstanding = flt(
				sum(
					max(flt(row.get("approved_amount")) - flt(row.get("funded_amount")), 0)
					* (flt(row.get("exchange_rate")) or 1)
					for row in approved_rows
				),
				2,
			)
		else:
			self.total_approved = 0
			if self.meta.has_field("total_variance"):
				self.total_variance = 0
			self.outstanding = 0
		self._set_currency_totals(rows, approved_rows)

	def total_requested_approved_rows(self, approved_rows) -> float:
		"""Company-currency requested total across approved rows only."""
		return self._base_sum(approved_rows, "requested_amount")

	@staticmethod
	def _base_sum(rows, fieldname: str) -> float:
		"""Sum a row amount in company currency.

		Falls back to the row-currency figure when no base twin is stored, which is
		what happens on an existing request saved before multicurrency and on any
		row whose currency is the company's own.
		"""
		total = 0.0
		for row in rows:
			base_field = f"base_{fieldname}"
			if row.meta.has_field(base_field) and flt(row.get(base_field)):
				total += flt(row.get(base_field))
			else:
				total += flt(row.get(fieldname)) * (flt(row.get("exchange_rate")) or 1)
		return flt(total, 2)

	def _set_currency_totals(self, rows, approved_rows) -> None:
		"""One row per currency, so a KES figure is never added to a USD one.

		The company-currency totals below this are the ones the approval decision
		and the payment gates use, because those need a single comparable number.
		This table is what the figures were actually asked for in, which is what a
		requester and an approver recognise.
		"""
		if not self.meta.has_field("currency_totals"):
			return
		base = company_currency(self.company)
		recorded = funding_approval_is_recorded(self.workflow_state)
		approved_names = {row.name for row in approved_rows}

		totals: dict[str, dict] = {}
		for row in rows:
			currency = row.get("currency") or base
			bucket = totals.setdefault(
				currency,
				{"requested": 0.0, "approved": 0.0, "funded": 0.0, "base_approved": 0.0},
			)
			rate = flt(row.get("exchange_rate")) or 1
			bucket["requested"] += flt(row.get("requested_amount"))
			if recorded and row.name in approved_names:
				bucket["approved"] += flt(row.get("approved_amount"))
				bucket["funded"] += flt(row.get("funded_amount"))
				bucket["base_approved"] += flt(row.get("base_approved_amount")) or (
					flt(row.get("approved_amount")) * rate
				)

		# A request entirely in the company currency has nothing to break down, and
		# one row repeating the totals below it would be noise.
		if set(totals) <= {base}:
			self.set("currency_totals", [])
			return

		self.set("currency_totals", [])
		# Company currency first, then alphabetical, so the sheet reads the same way
		# every time regardless of which request came in first.
		for currency in sorted(totals, key=lambda c: (c != base, c)):
			bucket = totals[currency]
			self.append(
				"currency_totals",
				{
					"currency": currency,
					"total_requested": flt(bucket["requested"], 2),
					"total_approved": flt(bucket["approved"], 2),
					"total_funded": flt(bucket["funded"], 2),
					"outstanding": flt(bucket["approved"] - bucket["funded"], 2),
					"base_total_approved": flt(bucket["base_approved"], 2),
				},
			)

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
			# A request holding more than one currency appears once per currency,
			# because each half is approved on its own and paid from its own bank
			# account. Two rows for the same request *and* currency is still a
			# duplicate and still wrong.
			key = (row.material_request, row.get("currency") or "")
			if key in seen:
				currency = row.get("currency")
				frappe.throw(
					_("Material Request {0} is included more than once in {1}.").format(
						frappe.bold(row.material_request), frappe.bold(currency)
					)
					if currency
					else _("Material Request {0} is included more than once.").format(
						frappe.bold(row.material_request)
					)
				)
			seen.add(key)
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
			requested = self._sync_row_currency(row, requested)
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
			self._sync_row_base_amounts(row)
			row.status = self._row_status_label(row)

	def _sync_row_currency(self, row, requested: float) -> float:
		"""Keep the row aligned with its own slice of the Material Request.

		One request may produce several rows, one per currency. Each row owns its
		currency, so the request is re-read and the matching slice taken rather
		than the whole request total being forced onto every row. Returns the
		requested amount in the row's currency.
		"""
		if not row.meta.has_field("currency"):
			return requested

		splits = material_request_currency_totals(row.material_request)
		if not splits:
			return requested

		# A row that has no currency yet belongs to the first slice, which is how a
		# request raised before multicurrency reads.
		if not row.currency:
			row.currency = splits[0]["currency"]

		match = next((s for s in splits if s["currency"] == row.currency), None)
		if not match:
			# The request no longer has lines in this currency: keep the row at zero
			# rather than silently repricing it into a currency nobody asked for.
			if row.meta.has_field("exchange_rate"):
				row.exchange_rate = row.exchange_rate or 1
			return 0.0

		if row.meta.has_field("exchange_rate"):
			row.exchange_rate = match["exchange_rate"]
		return match["amount"]

	def _sync_row_base_amounts(self, row) -> None:
		"""Mirror the row-currency amounts into their company-currency twins.

		The header totals and everything downstream of them are stated in company
		currency, so these twins are what keeps a foreign row comparable with a
		local one. For a company-currency row the rate is 1 and the twin is the
		same number, which is why nothing changed for existing requests.
		"""
		rate = flt(row.get("exchange_rate")) or 1
		for source, target in (
			("requested_amount", "base_requested_amount"),
			("approved_amount", "base_approved_amount"),
		):
			if row.meta.has_field(target):
				row.set(target, flt(flt(row.get(source)) * rate, 2))

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

	def _block_self_approval(self) -> None:
		"""Whoever raised the request cannot be the one who approves it.

		This ends in money leaving a bank account, so the person asking and the
		person agreeing have to be two people. Nothing enforced that: submitted_by
		and approved_by were both stamped with frappe.session.user, so one person
		holding both roles could raise and approve in a single sitting.

		Checked only as the request *enters* an approval state. A record approved
		before this rule existed keeps saving normally rather than becoming
		uneditable, and a later save by the submitter of an already-approved
		request is not a second approval.
		"""
		workflow = get_funding_workflow_map()
		if not workflow.is_approval_stamp_state(self.workflow_state):
			return
		previous = self.get_doc_before_save() if not self.is_new() else None
		if previous and workflow.is_approval_stamp_state(previous.workflow_state):
			return

		approver = self.approved_by or frappe.session.user
		if not self.submitted_by or approver != self.submitted_by:
			return

		# Name the role that is waiting. "Ask another approver" left the reader to
		# work out who that is, which on a site with several finance roles is not
		# obvious. The people holding it are deliberately not listed: a refusal
		# message is the wrong place to publish who holds a finance role, and any
		# list goes stale as soon as somebody joins or leaves.
		role = funding_approver_role()
		if not role:
			who = _("Ask another approver to review it.")
		elif another_approver_exists(role, exclude=self.submitted_by):
			who = _("Waiting on a <b>{0}</b>.").format(role)
		else:
			who = _(
				"Waiting on a <b>{0}</b>, and nobody else currently holds that role, "
				"so it has to be given to someone before this can move."
			).format(role)

		blocked_dialog(
			_("Someone else has to approve this"),
			_("A funding request cannot be approved by the person who raised it:"),
			[
				(
					_("Raised and approved by {0}").format(
						frappe.db.get_value("User", self.submitted_by, "full_name")
						or self.submitted_by
					),
					who
					+ " "
					+ _(
						"Segregation of duties is the control that stops one person "
						"moving money on their own."
					),
				)
			],
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
		from cgm_shipping.cgm_worldwide_shipping.customizations.funding import (
			material_request_payment_started,
		)

		return mr_row_workflow_state(
			self.workflow_state,
			row.approved_amount,
			row.funded_amount,
			payment_started=material_request_payment_started(self.name, row.material_request),
		)

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
