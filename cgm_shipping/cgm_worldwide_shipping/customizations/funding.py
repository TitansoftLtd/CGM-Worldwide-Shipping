"""Material Request funding workflow: Purpose, Project carry-through, Funding Request.

ERPNext already owns Material Request, purchasing, stock, Journal Entry, and
Payment Entry. Operational Expense is paid by Journal Entry (expense + bank).
Purchase still uses Purchase Order. Funding Request is Operational Expense only.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate, strip_html

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	FR_ROW_DECISION_APPROVED,
	FR_ROW_DECISION_PENDING,
	FR_ROW_DECISION_REJECTED,
	MATERIAL_REQUEST_TYPE_OPERATIONAL,
	MR_WORKFLOW_STATE_APPROVED,
	MR_WORKFLOW_STATE_DRAFT,
	MR_WORKFLOW_STATE_DISBURSED,
	MR_WORKFLOW_STATE_FIELD,
	MR_WORKFLOW_STATE_ON_FUNDING_REQUEST,
	MR_WORKFLOW_STATE_REJECTED,
	MR_WORKFLOW_STATE_SUBMITTED,
	MR_WORKFLOW_STATE_SUBMITTED_LEGACY,
	MR_WORKFLOW_STATE_UNFUNDED,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
	STEP_CREATE_PURCHASE_ORDER,
	STEP_DISBURSE,
	STEP_RECORD_PURCHASE_PAYMENT,
	STEP_SUBMIT_JOURNAL_ENTRY,
	STEP_SUBMIT_PURCHASE_ORDER,
	get_funding_workflow_map,
	get_material_request_state_names,
	pick_workflow_state,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.multicurrency import (
	company_currency,
	live_exchange_rate,
	material_request_currency_totals,
	normalize_material_request_currencies,
)


def mr_workflow_state_from_funding_request(
	fr_workflow_state: str | None, workflow=None, mr_workflow=None
) -> str:
	"""Write a Material Request workflow_state that exists on the live MR workflow."""
	wf = get_funding_workflow_map(workflow)
	mr_states = get_material_request_state_names(mr_workflow)
	if wf.is_rejected(fr_workflow_state):
		return pick_workflow_state(mr_states, "Rejected", default=MR_WORKFLOW_STATE_REJECTED)
	if wf.is_pending(fr_workflow_state):
		return pick_workflow_state(
			mr_states,
			"On Funding Request",
			fr_workflow_state,
			*wf.pending_states,
			"Pending",
			"Pending Approval",
			default=MR_WORKFLOW_STATE_ON_FUNDING_REQUEST,
		)
	if wf.is_disbursed(fr_workflow_state) or wf.is_fully_complete(fr_workflow_state):
		return pick_workflow_state(mr_states, "Disbursed", default=MR_WORKFLOW_STATE_DISBURSED)
	if wf.is_partial(fr_workflow_state):
		return pick_workflow_state(
			mr_states,
			wf.partial_state,
			"Partially Approved",
			"Approved",
			default=MR_WORKFLOW_STATE_APPROVED,
		)
	if wf.approval_is_recorded(fr_workflow_state):
		return pick_workflow_state(
			mr_states,
			fr_workflow_state,
			"Approved",
			default=MR_WORKFLOW_STATE_APPROVED,
		)
	return pick_workflow_state(
		mr_states, "On Funding Request", default=MR_WORKFLOW_STATE_ON_FUNDING_REQUEST
	)


def mr_row_workflow_state(
	fr_workflow_state: str | None,
	approved_amount,
	funded_amount,
	workflow=None,
	mr_workflow=None,
	*,
	payment_started: bool = False,
) -> str:
	"""The Material Request state for one row of a Funding Request.

	The request's own state is the starting point, then the row decides: a batch
	is "in progress" as soon as any row is, but a requester looking at their own
	Material Request needs to know about *their* row.

	* Paid in full: Disbursed, whatever the rest of the batch is doing.
	* Its entry or order raised but not yet paid (`payment_started`):
	  Disbursement in Progress, where the Material Request workflow has that state.
	* Nothing raised for it yet: Approved, even if other rows have moved on.
	"""
	mr_states = get_material_request_state_names(mr_workflow)
	state = mr_workflow_state_from_funding_request(
		fr_workflow_state, workflow=workflow, mr_workflow=mr_workflow
	)
	approved = pick_workflow_state(mr_states, "Approved", default=MR_WORKFLOW_STATE_APPROVED)
	disbursed = pick_workflow_state(mr_states, "Disbursed", default=MR_WORKFLOW_STATE_DISBURSED)
	in_progress = get_funding_workflow_map(workflow).disbursement_state
	in_progress = in_progress if in_progress and in_progress in mr_states else None
	if state not in (approved, in_progress):
		return state
	if flt(approved_amount) > 0 and flt(funded_amount) + 0.005 >= flt(approved_amount):
		return disbursed
	if in_progress and payment_started:
		return in_progress
	return approved


def material_request_payment_started(funding_request: str, material_request: str) -> bool:
	"""Is an entry or an order already raised for this request, paid or not?"""
	mr_type = frappe.db.get_value("Material Request", material_request, "material_request_type")
	if mr_type == MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return _open_journal_entry_exists(funding_request, material_request)
	if mr_type in PURCHASE_REQUEST_TYPES:
		return _open_purchase_order_exists(material_request)
	return False


def released_mr_workflow_state(material_request: str, mr_workflow=None) -> str:
	"""State to restore on a Material Request when it leaves a Funding Request."""
	mr_states = get_material_request_state_names(mr_workflow)
	mr_type = frappe.db.get_value("Material Request", material_request, "material_request_type")
	if mr_type == MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return pick_workflow_state(mr_states, "Unfunded", default=MR_WORKFLOW_STATE_UNFUNDED)
	return pick_workflow_state(
		mr_states,
		MR_WORKFLOW_STATE_SUBMITTED,
		MR_WORKFLOW_STATE_SUBMITTED_LEGACY,
		default=MR_WORKFLOW_STATE_SUBMITTED,
	)


def variance_amount(requested, approved) -> float:
	"""Approved minus requested. Negative = reduction, positive = increase."""
	return flt(approved) - flt(requested)


def funding_is_pending(workflow_state: str | None, workflow=None) -> bool:
	"""True while the Funding Request is waiting for the Funding Approver."""
	return get_funding_workflow_map(workflow).is_pending(workflow_state)


@frappe.whitelist()
def funding_request_is_pending_approval(workflow_state=None) -> bool:
	"""Form helper: unlock row decisions from the live workflow, not a label list."""
	return funding_is_pending(workflow_state)


def apply_batch_approve_to_pending_rows(rows) -> None:
	"""Header Approve means approve every row that was not explicitly rejected."""
	for row in rows:
		if row.get("decision") != FR_ROW_DECISION_PENDING:
			continue
		row.decision = FR_ROW_DECISION_APPROVED
		if flt(row.get("approved_amount")) == 0:
			row.approved_amount = flt(row.get("requested_amount"))


def funding_batch_is_partially_approved(rows, *, tolerance: float = 0.005) -> bool:
	"""True when Approve should land on Partially Approved, not Approved."""
	approved = [row for row in rows if row.get("decision") == FR_ROW_DECISION_APPROVED]
	rejected = [row for row in rows if row.get("decision") == FR_ROW_DECISION_REJECTED]
	if rejected and approved:
		return True
	return any(
		row.get("decision") == FR_ROW_DECISION_APPROVED
		and flt(row.get("approved_amount")) + tolerance < flt(row.get("requested_amount"))
		for row in rows
	)


def funding_approval_is_recorded(workflow_state: str | None, workflow=None) -> bool:
	"""True only after a Funding Approver has approved the batch."""
	return get_funding_workflow_map(workflow).approval_is_recorded(workflow_state)


def funding_is_approved(workflow_state: str | None, docstatus: int | None = 0, workflow=None) -> bool:
	wf = get_funding_workflow_map(workflow)
	if wf.is_terminal(workflow_state):
		return False
	if not wf.approval_is_recorded(workflow_state):
		return False
	return cint_docstatus(docstatus) == 1


def funding_progress_state(
	current: str | None,
	total_funded: float,
	total_approved: float,
	workflow=None,
	*,
	disbursement_started: bool = False,
	rows_fully_paid: bool = False,
	approved_state: str | None = None,
) -> str | None:
	"""Payment-driven Funding Request state.

	Draft Journal Entries / Purchase Orders move the batch to Disbursement in
	Progress. Submitted Journal Entries and recorded PO payments move rows (and
	the batch when fully paid) to Disbursed.

	`rows_fully_paid` settles it when every approved row is paid in its own
	currency. The company-currency totals cannot be trusted for that: a USD row
	approved at one rate and paid at another leaves them a few shillings apart
	in either direction, and the request then sat in Disbursement in Progress
	for ever with every row paid.
	"""
	wf = get_funding_workflow_map(workflow)
	if current not in wf.progress_states():
		return current
	funded = flt(total_funded)
	approved = flt(total_approved)
	disbursed = next(iter(wf.disbursed_states()), None)
	if rows_fully_paid or (approved > 0 and funded + 0.005 >= approved):
		return disbursed or current
	if funded > 0 or disbursement_started:
		return wf.disbursement_state or current
	# Nothing paid and nothing raised. A request that had moved on - its entry
	# cancelled, its draft deleted - goes back to where approval left it, not to
	# "in progress" with no document behind the words.
	if wf.is_disbursed(current) or current == wf.disbursement_state:
		return approved_state or wf.disbursement_state or current
	return current


def _approval_state(fr) -> str | None:
	"""The state approval left this request in: partially approved, or approved."""
	wf = get_funding_workflow_map()
	if wf.partial_state and funding_batch_is_partially_approved(fr.material_requests):
		return wf.partial_state
	return next(iter(sorted(wf.approve_next_states)), None)


def funding_request_disbursement_started(funding_request: str) -> bool:
	"""True when an open Journal Entry or Purchase Order exists for approved rows."""
	if not funding_request or not frappe.db.exists("Funding Request", funding_request):
		return False
	fr = frappe.get_doc("Funding Request", funding_request)
	for row in fr.material_requests:
		if getattr(row, "decision", None) != FR_ROW_DECISION_APPROVED:
			continue
		if not row.material_request:
			continue
		if flt(row.approved_amount) - flt(row.funded_amount) <= 0:
			continue
		mr_type = frappe.db.get_value(
			"Material Request", row.material_request, "material_request_type"
		)
		if mr_type == MATERIAL_REQUEST_TYPE_OPERATIONAL:
			if _open_journal_entry_exists(funding_request, row.material_request):
				return True
		elif mr_type in PURCHASE_REQUEST_TYPES:
			if _open_purchase_order_exists(row.material_request):
				return True
	return False


PURCHASE_REQUEST_TYPES = frozenset({"Purchase", "Subcontracting"})
FUNDING_MATERIAL_REQUEST_TYPES = frozenset({"Purchase", MATERIAL_REQUEST_TYPE_OPERATIONAL})


def material_request_purchase_is_funding_approved(material_request: str) -> bool:
	"""Purchase follows procurement. It does not wait on a Funding Request."""
	return True


def assert_material_request_may_create_purchase_document(material_request: str) -> None:
	if material_request_purchase_is_funding_approved(material_request):
		return
	frappe.throw(
		_(
			"Material Request {0} must be on an approved Funding Request "
			"before a Purchase Order or quotation can be created."
		).format(frappe.bold(material_request))
	)


def on_purchase_document_validate(doc, method=None) -> None:
	if cint_docstatus(doc.docstatus) == 2:
		return
	_reject_shipping_line_supplier_on_po(doc)
	if not doc.is_new() and cint_docstatus(doc.docstatus) == 1:
		return
	seen = set()
	for row in doc.get("items") or []:
		mr_name = row.get("material_request")
		if not mr_name or mr_name in seen:
			continue
		seen.add(mr_name)
		assert_material_request_may_create_purchase_document(mr_name)


def _reject_shipping_line_supplier_on_po(doc) -> None:
	if doc.doctype != "Purchase Order" or not doc.get("supplier"):
		return
	if not frappe.db.has_column("Supplier", "custom_is_shipping_line"):
		return
	if frappe.db.get_value("Supplier", doc.supplier, "custom_is_shipping_line"):
		frappe.throw(
			_("Supplier {0} is marked as a Shipping Line and cannot be used on Purchase Orders.").format(
				frappe.bold(doc.supplier)
			)
		)


@frappe.whitelist()
def make_purchase_order(source_name, target_doc=None, args=None):
	assert_material_request_may_create_purchase_document(source_name)
	from erpnext.stock.doctype.material_request.material_request import (
		make_purchase_order as erpnext_make_purchase_order,
	)

	po = erpnext_make_purchase_order(source_name, target_doc=target_doc, args=args)
	_ensure_purchase_order_required_by(po)
	return po


@frappe.whitelist()
def make_request_for_quotation(source_name, target_doc=None):
	assert_material_request_may_create_purchase_document(source_name)
	from erpnext.stock.doctype.material_request.material_request import (
		make_request_for_quotation as erpnext_make_request_for_quotation,
	)

	return erpnext_make_request_for_quotation(source_name, target_doc=target_doc)


@frappe.whitelist()
def make_supplier_quotation(source_name, target_doc=None):
	assert_material_request_may_create_purchase_document(source_name)
	from erpnext.stock.doctype.material_request.material_request import (
		make_supplier_quotation as erpnext_make_supplier_quotation,
	)

	return erpnext_make_supplier_quotation(source_name, target_doc=target_doc)


@frappe.whitelist()
def make_purchase_order_based_on_supplier(source_name, target_doc=None, args=None):
	assert_material_request_may_create_purchase_document(source_name)
	from erpnext.stock.doctype.material_request.material_request import (
		make_purchase_order_based_on_supplier as erpnext_make_po_by_supplier,
	)

	po = erpnext_make_po_by_supplier(source_name, target_doc=target_doc, args=args)
	_ensure_purchase_order_required_by(po)
	return po


def _ensure_purchase_order_required_by(po) -> None:
	"""ERPNext blanks Required By when the Material Request date is already past."""
	if not po:
		return
	required_by = nowdate()
	header = po.get("schedule_date")
	if not header or getdate(header) < getdate(required_by):
		if isinstance(po, dict):
			po["schedule_date"] = required_by
		else:
			po.schedule_date = required_by
	for item in po.get("items") or []:
		item_date = item.get("schedule_date")
		if not item_date or getdate(item_date) < getdate(required_by):
			if isinstance(item, dict):
				item["schedule_date"] = po.get("schedule_date")
			else:
				item.schedule_date = po.schedule_date


def cint_docstatus(docstatus) -> int:
	try:
		return int(docstatus or 0)
	except (TypeError, ValueError):
		return 0


def get_material_request_total(material_request) -> float:
	"""Requested amount = sum of Material Request Item.amount.

	Items are the source of truth. A legacy header custom_requested_amount is
	used only when the Items table has no amounts (historical rows).
	"""
	if not material_request:
		return 0.0
	if isinstance(material_request, str):
		total = flt(
			sum(
				flt(row.amount)
				for row in frappe.get_all(
					"Material Request Item",
					filters={"parent": material_request},
					fields=["amount"],
				)
			)
		)
		if total:
			return total
		return _legacy_header_requested_amount(material_request)
	total = flt(sum(flt(row.amount) for row in (material_request.get("items") or [])))
	if total:
		return total
	legacy = material_request.get("custom_requested_amount")
	if legacy not in (None, ""):
		return flt(legacy)
	return 0.0


def _legacy_header_requested_amount(material_request: str) -> float:
	if not frappe.db.has_column("Material Request", "custom_requested_amount"):
		return 0.0
	value = frappe.db.get_value("Material Request", material_request, "custom_requested_amount")
	return flt(value) if value not in (None, "") else 0.0


def get_material_request_item_summary(material_request) -> str:
	"""Item names on the request — classification lives on Item, not Purpose."""
	if not material_request:
		return ""
	if isinstance(material_request, str):
		rows = frappe.get_all(
			"Material Request Item",
			filters={"parent": material_request},
			fields=["item_code", "item_name"],
			order_by="idx asc",
		)
	else:
		rows = material_request.get("items") or []
	names = []
	seen = set()
	for row in rows:
		label = (row.get("item_name") or row.get("item_code") or "").strip()
		if label and label not in seen:
			seen.add(label)
			names.append(label)
	return ", ".join(names)


def get_material_request_description(material_request) -> str:
	"""Notes from item descriptions; legacy header text as fallback."""
	if not material_request:
		return ""
	if isinstance(material_request, str):
		rows = frappe.get_all(
			"Material Request Item",
			filters={"parent": material_request},
			fields=["description"],
			order_by="idx asc",
		)
		legacy = frappe.db.get_value(
			"Material Request", material_request, "custom_request_description"
		)
	else:
		rows = material_request.get("items") or []
		legacy = material_request.get("custom_request_description")
	parts = []
	for row in rows:
		text = strip_html((row.get("description") or "").strip())
		if text and text not in parts:
			parts.append(text)
	if parts:
		return " - ".join(parts)
	legacy = (legacy or "").strip()
	return legacy or get_material_request_item_summary(material_request)


def get_material_request_requester_name(material_request) -> str | None:
	"""Display name for Funding Request Requester column.

	Operational Expense uses Employee; Purchase/Subcontracting use Requested By.
	"""
	if not material_request:
		return None
	if isinstance(material_request, str):
		fields = ["custom_employee", "custom_requested_by", "custom_requested_by_name"]
		mr = frappe.db.get_value("Material Request", material_request, fields, as_dict=True)
	else:
		mr = material_request
	if not mr:
		return None
	if mr.get("custom_employee"):
		return frappe.db.get_value("Employee", mr.custom_employee, "employee_name")
	if mr.get("custom_requested_by_name"):
		return mr.custom_requested_by_name
	if mr.get("custom_requested_by"):
		return frappe.db.get_value("User", mr.custom_requested_by, "full_name")
	return None


def get_material_request_project(material_request) -> str | None:
	"""Header custom_project, else the item-level Project accounting dimension."""
	if not material_request:
		return None
	name = (
		material_request
		if isinstance(material_request, str)
		else material_request.name
	)
	project = frappe.db.get_value("Material Request", name, "custom_project")
	if project:
		return project
	return frappe.db.get_value(
		"Material Request Item",
		{"parent": name, "project": ["is", "set"]},
		"project",
	)


# ── Material Request ─────────────────────────────────────────────────────────


def on_material_request_validate(doc, method=None) -> None:
	_set_requester_defaults(doc)
	_copy_header_project_to_items(doc)
	_clear_warehouse_for_operational_expense(doc)
	_set_default_funding_workflow_state(doc)
	_validate_operational_expense_request(doc)
	_keep_multicurrency_on(doc)
	normalize_material_request_currencies(doc)


def _keep_multicurrency_on(doc) -> None:
	"""Operational Expense requests are always multicurrency.

	The box used to be something a requester could untick. Doing so forced every
	line back to the company currency, and a USD shipping line or KPA charge then
	had to be converted by hand before it was typed - the thing multicurrency was
	added to stop. The field is read-only on the form; this holds it for requests
	saved any other way, and before the currencies are normalised below.
	"""
	if doc.get("material_request_type") != MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return
	if doc.meta.has_field("custom_multicurrency"):
		doc.custom_multicurrency = 1


def on_material_request_on_submit(doc, method=None) -> None:
	"""Align funding Workflow State after ERPNext submit (does not replace ERPNext status)."""
	if not doc.meta.has_field(MR_WORKFLOW_STATE_FIELD):
		return
	current = (doc.get(MR_WORKFLOW_STATE_FIELD) or "").strip()
	mr_states = get_material_request_state_names()
	draft = pick_workflow_state(mr_states, "Draft", default=MR_WORKFLOW_STATE_DRAFT)
	if current and current not in {draft, ""}:
		return
	next_state = (
		pick_workflow_state(mr_states, "Unfunded", default=MR_WORKFLOW_STATE_UNFUNDED)
		if doc.get("material_request_type") == MATERIAL_REQUEST_TYPE_OPERATIONAL
		else pick_workflow_state(
			mr_states,
			MR_WORKFLOW_STATE_SUBMITTED,
			MR_WORKFLOW_STATE_SUBMITTED_LEGACY,
			default=MR_WORKFLOW_STATE_SUBMITTED,
		)
	)
	doc.db_set(MR_WORKFLOW_STATE_FIELD, next_state, update_modified=False)


def _set_default_funding_workflow_state(doc) -> None:
	if not doc.meta.has_field(MR_WORKFLOW_STATE_FIELD):
		return
	if doc.get(MR_WORKFLOW_STATE_FIELD):
		return
	if cint_docstatus(doc.docstatus) >= 1:
		return
	doc.set(
		MR_WORKFLOW_STATE_FIELD,
		pick_workflow_state(get_material_request_state_names(), "Draft", default=MR_WORKFLOW_STATE_DRAFT),
	)


def _set_requester_defaults(doc) -> None:
	if not doc.get("custom_requested_by"):
		doc.custom_requested_by = frappe.session.user
	if doc.get("material_request_type") != MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return
	if doc.get("custom_employee"):
		return
	employee = frappe.db.get_value(
		"Employee",
		{"user_id": doc.custom_requested_by or frappe.session.user, "status": "Active"},
		"name",
	)
	if employee:
		doc.custom_employee = employee


def _validate_operational_expense_request(doc) -> None:
	if doc.get("material_request_type") != MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return
	if not doc.get("custom_employee"):
		frappe.throw(
			_("Set Employee on Operational Expense requests. Link your user on the Employee record, or pick the employee who receives the cash.")
		)


def _copy_header_project_to_items(doc) -> None:
	"""Reuse Material Request Item.project (accounting dimension). Do not add another."""
	header_project = doc.get("custom_project")
	if header_project:
		for item in doc.get("items") or []:
			if not item.get("project"):
				item.project = header_project
		return
	item_projects = {item.project for item in (doc.get("items") or []) if item.get("project")}
	if len(item_projects) == 1:
		doc.custom_project = item_projects.pop()


def _clear_warehouse_for_operational_expense(doc) -> None:
	"""Operational Expense is cash/service, not a stock indent. ERPNext still
	fills warehouse from Item / Item Group / Stock Settings defaults."""
	if doc.get("material_request_type") != MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return
	if doc.get("set_warehouse"):
		doc.set_warehouse = None
	for item in doc.get("items") or []:
		if item.get("warehouse"):
			item.warehouse = None


def copy_project_to_stock_entry(doc, method=None) -> None:
	"""Carry Project from the originating Material Request onto Stock Entry."""
	if not doc.get("project"):
		mrs = {
			row.material_request
			for row in (doc.get("items") or [])
			if row.get("material_request")
		}
		if len(mrs) == 1:
			doc.project = get_material_request_project(next(iter(mrs)))
	if not doc.get("project"):
		return
	for row in doc.get("items") or []:
		if not row.get("project"):
			row.project = doc.project


def on_payment_entry_on_submit(doc, method=None) -> None:
	sync_funding_requests_touched_by_payment_entry(doc)


def on_payment_entry_on_cancel(doc, method=None) -> None:
	sync_funding_requests_touched_by_payment_entry(doc)


def on_journal_entry_on_submit(doc, method=None) -> None:
	sync_funding_request_paid_amounts(doc.get("custom_funding_request"))


def on_journal_entry_after_insert(doc, method=None) -> None:
	sync_funding_request_paid_amounts(doc.get("custom_funding_request"))


def on_journal_entry_on_cancel(doc, method=None) -> None:
	sync_funding_request_paid_amounts(doc.get("custom_funding_request"))


def on_journal_entry_after_delete(doc, method=None) -> None:
	"""A deleted draft leaves its row with no entry again, which changes what is pending."""
	sync_funding_request_paid_amounts(doc.get("custom_funding_request"))


def on_purchase_order_change(doc, method=None) -> None:
	"""Submitting, cancelling or deleting an order changes what the request waits on."""
	sync_funding_request_from_purchase_order(doc)


def on_purchase_order_after_insert(doc, method=None) -> None:
	sync_funding_request_from_purchase_order(doc)


def sync_funding_request_from_purchase_order(doc) -> None:
	fr_name = doc.get("custom_funding_request") if doc.meta.has_field("custom_funding_request") else None
	if not fr_name:
		for row in doc.get("items") or []:
			mr_name = row.get("material_request")
			if not mr_name:
				continue
			fr_name = frappe.db.get_value("Material Request", mr_name, "custom_funding_request")
			if fr_name:
				break
	if fr_name:
		sync_funding_request_paid_amounts(fr_name)


def sync_funding_requests_touched_by_payment_entry(doc) -> None:
	"""Payments against a Purchase Invoice or, as an advance, against the Purchase
	Order itself. Operational Expense is paid via Journal Entry, not from here."""
	seen = set()
	for ref in doc.get("references") or []:
		fr_name = None
		if ref.reference_doctype == "Purchase Invoice" and ref.reference_name:
			fr_name = _funding_request_from_purchase_invoice(ref.reference_name)
		elif ref.reference_doctype == "Purchase Order" and ref.reference_name:
			fr_name = _funding_request_from_purchase_order(ref.reference_name)
		if fr_name and fr_name not in seen:
			seen.add(fr_name)
			sync_funding_request_paid_amounts(fr_name)


def sync_funding_request_paid_amounts(funding_request: str | None) -> None:
	"""Funded Amount is cash actually paid, not draft Journal Entries or POs."""
	if not funding_request or not frappe.db.exists("Funding Request", funding_request):
		return
	# Cancelling a request cancels its own entries and orders. Each of those calls
	# back here, and re-saving the request from a fresh copy mid-cancel would fight
	# the cancel that is already writing it.
	if frappe.flags.get("cgm_funding_cancelling") == funding_request:
		return
	fr = frappe.get_doc("Funding Request", funding_request)
	changed = False
	for row in fr.material_requests:
		if not row.material_request:
			continue
		paid, paid_base = paid_amount_for_material_request(
			fr.name, row.material_request, row.get("currency")
		)
		if abs(flt(row.funded_amount) - flt(paid)) > 0.005:
			row.funded_amount = paid
			changed = True
		if row.meta.has_field("base_funded_amount") and (
			abs(flt(row.get("base_funded_amount")) - flt(paid_base)) > 0.005
		):
			row.base_funded_amount = paid_base
			changed = True
	fr.calculate_totals()
	approved_rows = [
		row
		for row in fr.material_requests
		if row.material_request and getattr(row, "decision", None) == FR_ROW_DECISION_APPROVED
	]
	next_state = funding_progress_state(
		fr.workflow_state,
		fr.total_funded,
		fr.total_approved,
		disbursement_started=funding_request_disbursement_started(funding_request),
		rows_fully_paid=bool(approved_rows)
		and all(flt(row.approved_amount) - flt(row.funded_amount) <= 0.005 for row in approved_rows),
		approved_state=_approval_state(fr),
	)
	state_changed = next_state != fr.workflow_state
	if changed:
		fr.flags.ignore_validate_update_after_submit = True
		fr.save(ignore_permissions=True)
	if state_changed:
		# Payment-driven states are not workflow Actions; set_value skips
		# "transition not allowed" when reversing partial payment.
		frappe.db.set_value(
			"Funding Request",
			fr.name,
			"workflow_state",
			next_state,
			update_modified=False,
		)
		fr.workflow_state = next_state
	# Every time, not only when an amount moved: a draft entry or an order being
	# raised, submitted or deleted changes what is pending without paying anything.
	store_pending_step(fr)
	# Likewise every time: a Material Request now reads "in progress" from the
	# moment its entry or order is raised, which moves no amount and no state.
	fr.sync_material_request_links()


def funding_payment_documents(funding_request: str) -> list[dict]:
	"""The entries and orders tied to this request that are still live.

	Only documents carrying this request's own link. A Purchase Order raised
	straight from the Material Request and never adopted by this request belongs
	to procurement, not to this request, and is left out.
	"""
	documents = []
	if frappe.db.has_column("Journal Entry", "custom_funding_request"):
		for je in frappe.get_all(
			"Journal Entry",
			filters={"custom_funding_request": funding_request, "docstatus": ["<", 2]},
			fields=["name", "docstatus", "total_debit", "custom_material_request"],
			order_by="creation asc",
		):
			documents.append(
				{
					"doctype": "Journal Entry",
					"name": je.name,
					"docstatus": cint(je.docstatus),
					"material_request": je.get("custom_material_request"),
					"amount": flt(je.total_debit),
				}
			)
	if frappe.get_meta("Purchase Order").has_field("custom_funding_request"):
		for po in frappe.get_all(
			"Purchase Order",
			filters={"custom_funding_request": funding_request, "docstatus": ["<", 2]},
			fields=["name", "docstatus", "base_grand_total"],
			order_by="creation asc",
		):
			requests = frappe.get_all(
				"Purchase Order Item",
				filters={"parent": po.name, "material_request": ["is", "set"]},
				pluck="material_request",
				distinct=True,
			)
			documents.append(
				{
					"doctype": "Purchase Order",
					"name": po.name,
					"docstatus": cint(po.docstatus),
					"material_request": ", ".join(requests),
					"amount": flt(po.base_grand_total),
				}
			)
	return documents


@frappe.whitelist()
def get_funding_cancel_impact(funding_request: str) -> dict:
	"""What cancelling this request will delete and cancel, for the confirmation."""
	frappe.has_permission("Funding Request", "read", doc=funding_request, throw=True)
	fr = frappe.get_doc("Funding Request", funding_request)
	documents = funding_payment_documents(fr.name)
	return {
		"delete": [doc for doc in documents if doc["docstatus"] == 0],
		"cancel": [doc for doc in documents if doc["docstatus"] == 1],
		"material_requests": list(
			dict.fromkeys(row.material_request for row in fr.material_requests if row.material_request)
		),
		"currency": company_currency(fr.company),
	}


def cancel_funding_payment_documents(fr) -> dict:
	"""Take a request's entries and orders with it when the request is cancelled.

	A cancelled Funding Request used to be impossible once anything was posted -
	Frappe refuses to cancel a document that submitted ones point at - and when it
	was possible it left its drafts behind, still claiming the Material Request.

	* A **draft** entry or order is deleted. It never took effect.
	* A **submitted** one is cancelled, which reverses its ledger postings and, for
	  an order, hands the ordered quantity back to the Material Request.
	* Either way the Material Request is let go: a cancelled document keeps its
	  link to this request, as the record of what was undone, but no longer points
	  at the Material Request, which is then free to be funded again.

	All or nothing. An entry in a closed period, or an order that already has a
	receipt or an invoice, cannot be cancelled; the error stops the whole cancel
	and nothing is changed. The person cancelling needs permission to cancel the
	submitted documents themselves.
	"""
	documents = funding_payment_documents(fr.name)
	deleted, cancelled = [], []
	for doc in documents:
		if doc["docstatus"] != 1:
			continue
		frappe.has_permission(doc["doctype"], "cancel", doc=doc["name"], throw=True)
		# ERPNext will cancel an order that has been paid, and leaves the payment
		# standing as an unallocated advance. A Journal Entry is reversed by its own
		# cancellation; a Payment Entry is not, so the money would be out of the
		# bank with no request and no order to show for it. That has to be dealt
		# with deliberately, on the payment, before the request can go.
		if doc["doctype"] == "Purchase Order":
			payments = _payments_against_purchase_order(doc["name"])
			if payments:
				frappe.throw(
					_(
						"{0} cannot be cancelled: Purchase Order {1} has been paid ({2}). "
						"Cancel that payment first, then cancel the request."
					).format(frappe.bold(fr.name), frappe.bold(doc["name"]), ", ".join(payments)),
					title=_("Payment already made"),
				)

	frappe.flags.cgm_funding_cancelling = fr.name
	try:
		for doc in documents:
			if doc["docstatus"] == 0:
				frappe.delete_doc(doc["doctype"], doc["name"], ignore_permissions=True, force=True)
				deleted.append(doc["name"])
				continue
			document = frappe.get_doc(doc["doctype"], doc["name"])
			document.cancel()
			_unlink_from_material_request(document)
			cancelled.append(doc["name"])
	finally:
		frappe.flags.cgm_funding_cancelling = None
	return {"deleted": deleted, "cancelled": cancelled}


def _payments_against_purchase_order(purchase_order: str) -> list[str]:
	"""Submitted Payment Entries against this order or against invoices raised from it."""
	rows = frappe.db.sql(
		"""
		select distinct pe.name
		from `tabPayment Entry Reference` per
		inner join `tabPayment Entry` pe on pe.name = per.parent
		where pe.docstatus = 1 and per.allocated_amount > 0
			and (
				(per.reference_doctype = 'Purchase Order' and per.reference_name = %(po)s)
				or (
					per.reference_doctype = 'Purchase Invoice'
					and per.reference_name in (
						select pii.parent from `tabPurchase Invoice Item` pii
						where pii.purchase_order = %(po)s and pii.docstatus = 1
					)
				)
			)
		order by pe.name
		""",
		{"po": purchase_order},
	)
	return [row[0] for row in rows]


def _unlink_from_material_request(document) -> None:
	"""Stop a cancelled entry or order pointing at its Material Request."""
	if document.doctype == "Journal Entry":
		if document.meta.has_field("custom_material_request") and document.get("custom_material_request"):
			frappe.db.set_value(
				"Journal Entry", document.name, "custom_material_request", None, update_modified=False
			)
		return
	if document.doctype == "Purchase Order":
		for item in document.get("items") or []:
			if item.get("material_request"):
				frappe.db.set_value(
					"Purchase Order Item",
					item.name,
					{"material_request": None, "material_request_item": None},
					update_modified=False,
				)


def funding_pending_step(fr) -> str:
	"""What this request is waiting on, as the name of the action that does it.

	Read off the rows by what each one is for. An Operational Expense row is paid
	by Journal Entry and a Purchase row through its Purchase Order, so the same
	"unpaid" means a different next step depending on the row.

	The earliest unfinished step across the rows wins: a document still to be
	raised comes before one waiting to be submitted, which comes before one
	waiting to be paid. Empty when nothing is pending.
	"""
	if cint_docstatus(fr.docstatus) != 1 or not funding_is_approved(fr.workflow_state, fr.docstatus):
		return ""
	if get_funding_workflow_map().is_fully_complete(fr.workflow_state):
		return ""
	needs_entry = needs_order = draft_entry = draft_order = unpaid_order = False
	for row in fr.material_requests:
		if not row.material_request or getattr(row, "decision", None) != FR_ROW_DECISION_APPROVED:
			continue
		if flt(row.approved_amount) - flt(row.funded_amount) <= 0.005:
			continue
		mr_type = frappe.db.get_value("Material Request", row.material_request, "material_request_type")
		if mr_type == MATERIAL_REQUEST_TYPE_OPERATIONAL:
			if _draft_journal_entry(fr.name, row.material_request, row.get("currency")):
				draft_entry = True
			else:
				needs_entry = True
		elif mr_type in PURCHASE_REQUEST_TYPES:
			order = _open_purchase_order_name(row.material_request)
			if not order:
				needs_order = True
			elif cint(frappe.db.get_value("Purchase Order", order, "docstatus")) == 0:
				draft_order = True
			else:
				unpaid_order = True
	if needs_entry:
		return STEP_DISBURSE
	if needs_order:
		return STEP_CREATE_PURCHASE_ORDER
	if draft_entry:
		return STEP_SUBMIT_JOURNAL_ENTRY
	if draft_order:
		return STEP_SUBMIT_PURCHASE_ORDER
	if unpaid_order:
		return STEP_RECORD_PURCHASE_PAYMENT
	return ""


def store_pending_step(fr) -> str:
	"""Write the pending step on the request when it has changed. Returns it."""
	if not fr.meta.has_field("pending_step"):
		return ""
	step = funding_pending_step(fr)
	if (frappe.db.get_value("Funding Request", fr.name, "pending_step") or "") != step:
		frappe.db.set_value("Funding Request", fr.name, "pending_step", step, update_modified=False)
	fr.pending_step = step
	return step


def paid_amount_for_material_request(
	funding_request: str, material_request: str, currency: str | None = None
) -> tuple[float, float]:
	"""Amount paid as (request currency, company currency)."""
	mr_type = frappe.db.get_value("Material Request", material_request, "material_request_type")
	if mr_type == MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return _paid_against_journal_entries(funding_request, material_request, currency)
	if mr_type in PURCHASE_REQUEST_TYPES:
		# Purchase Orders are raised in the company currency by this flow, so the
		# two figures are the same number.
		paid = _paid_against_purchase_orders(material_request)
		return paid, paid
	return 0.0, 0.0


def _paid_against_journal_entries(
	funding_request: str, material_request: str, currency: str | None = None
) -> tuple[float, float]:
	"""What was actually paid, as (request currency, company currency).

	Both figures are needed and they are not interchangeable. `jea.debit` is always
	company currency; `jea.debit_in_account_currency` is the account's own. A row
	closes on the request-currency figure, because a rate movement between approval
	and payment would otherwise leave a fully paid USD row looking short in KES and
	the request would never reach fully disbursed. The company-currency figure is
	what the header totals and the ledger reconcile on.
	"""
	if not frappe.db.has_column("Journal Entry", "custom_material_request"):
		return 0.0, 0.0
	entries = frappe.get_all(
		"Journal Entry",
		filters={
			"custom_funding_request": funding_request,
			"custom_material_request": material_request,
			"docstatus": 1,
		},
		pluck="name",
	)
	if not entries:
		return 0.0, 0.0
	company = frappe.db.get_value("Material Request", material_request, "company")
	base = company_currency(company)
	request_currency = currency or base
	# A mixed request has one entry per currency against the same request, so the
	# entries for the other half must not be counted here.
	in_currency_entries = _entries_in_currency(entries, request_currency)
	if in_currency_entries:
		entries = in_currency_entries
	rows = frappe.db.sql(
		"""
		select jea.account_currency, jea.debit_in_account_currency, jea.debit
		from `tabJournal Entry Account` jea
		inner join `tabJournal Entry` je on je.name = jea.parent
		where je.docstatus = 1
			and je.name in %(entries)s
			and jea.debit_in_account_currency > 0
		""",
		{"entries": entries},
		as_dict=True,
	)
	paid_base = flt(sum(flt(row.debit) for row in rows))
	# Prefer a line actually written in the request currency; fall back to the
	# company-currency total when the whole entry was posted in base.
	in_currency = flt(
		sum(
			flt(row.debit_in_account_currency)
			for row in rows
			if (row.account_currency or base) == request_currency
		)
	)
	if request_currency == base or not in_currency:
		return paid_base if request_currency == base else in_currency, paid_base
	return in_currency, paid_base


def _paid_against_purchase_orders(material_request: str) -> float:
	purchase_orders = frappe.get_all(
		"Purchase Order Item",
		filters={"material_request": material_request, "docstatus": 1},
		pluck="parent",
	)
	if not purchase_orders:
		return 0.0
	orders = list(set(purchase_orders))
	against_invoices = frappe.db.sql(
		"""
		select coalesce(sum(allocated_amount), 0)
		from (
			select distinct per.parent, per.idx, per.allocated_amount
			from `tabPayment Entry Reference` per
			inner join `tabPayment Entry` pe on pe.name = per.parent
			inner join `tabPurchase Invoice Item` pii on pii.parent = per.reference_name
			where pe.docstatus = 1
				and per.reference_doctype = 'Purchase Invoice'
				and pii.docstatus = 1
				and pii.purchase_order in %(purchase_orders)s
		) paid_rows
		""",
		{"purchase_orders": orders},
	)
	# A supplier is often paid up front, against the order, before any invoice
	# exists. That payment was not counted, so a request whose order had been
	# paid in full still read as unpaid. When the invoice arrives ERPNext moves
	# the allocation from the order's row to the invoice's, so adding the two
	# never counts the same money twice.
	against_orders = frappe.db.sql(
		"""
		select coalesce(sum(per.allocated_amount), 0)
		from `tabPayment Entry Reference` per
		inner join `tabPayment Entry` pe on pe.name = per.parent
		where pe.docstatus = 1
			and per.reference_doctype = 'Purchase Order'
			and per.reference_name in %(purchase_orders)s
		""",
		{"purchase_orders": orders},
	)
	return flt(against_invoices[0][0] if against_invoices else 0) + flt(
		against_orders[0][0] if against_orders else 0
	)


def _funding_request_from_purchase_order(purchase_order: str) -> str | None:
	if frappe.get_meta("Purchase Order").has_field("custom_funding_request"):
		linked = frappe.db.get_value("Purchase Order", purchase_order, "custom_funding_request")
		if linked:
			return linked
	for mr_name in frappe.get_all(
		"Purchase Order Item",
		filters={"parent": purchase_order, "material_request": ["is", "set"]},
		pluck="material_request",
		distinct=True,
	):
		fr_name = frappe.db.get_value("Material Request", mr_name, "custom_funding_request")
		if fr_name:
			return fr_name
	return None


def _funding_request_from_purchase_invoice(purchase_invoice: str) -> str | None:
	mrs = [
		row[0]
		for row in frappe.db.sql(
			"""
			select distinct poi.material_request
			from `tabPurchase Invoice Item` pii
			inner join `tabPurchase Order Item` poi on poi.parent = pii.purchase_order
			where pii.parent = %s
				and poi.material_request is not null
				and poi.material_request != ''
			""",
			purchase_invoice,
		)
		if row and row[0]
	]
	for mr_name in mrs:
		fr_name = frappe.db.get_value("Material Request", mr_name, "custom_funding_request")
		if fr_name:
			return fr_name
	return None


# ── Funding Request helpers ──────────────────────────────────────────────────


def fetch_material_request_rows(material_request: str) -> list[dict]:
	"""One Funding Request row per currency on the request.

	A request with KES and USD lines becomes two rows. They are approved
	separately and paid separately, because a Journal Entry takes money from one
	bank account held in one currency: there is no single payment that settles
	both halves.
	"""
	base = fetch_material_request_details(material_request)
	if not base:
		return []
	splits = material_request_currency_totals(material_request)
	if not splits:
		return [base]
	rows = []
	for split in splits:
		row = dict(base)
		row.update(
			{
				"currency": split["currency"],
				"exchange_rate": split["exchange_rate"],
				"requested_amount": split["amount"],
				"base_requested_amount": split["base_amount"],
			}
		)
		rows.append(row)
	return rows


def fetch_material_request_details(material_request: str) -> dict:
	if not material_request:
		return {}
	mr = frappe.get_doc("Material Request", material_request)
	requested = get_material_request_total(mr)
	description = get_material_request_description(mr)
	item_summary = get_material_request_item_summary(mr)
	requester_name = get_material_request_requester_name(mr)
	return {
		"material_request": mr.name,
		"employee": mr.get("custom_employee"),
		"employee_name": requester_name,
		"item_summary": item_summary,
		"description": description,
		"project": mr.get("custom_project") or get_material_request_project(mr.name),
		"requested_amount": requested,
		"approved_amount": 0,
		"base_approved_amount": 0,
		"variance": 0,
		"funded_amount": 0,
		"base_funded_amount": 0,
		"status": pick_workflow_state(
			get_material_request_state_names(),
			"On Funding Request",
			default=MR_WORKFLOW_STATE_ON_FUNDING_REQUEST,
		),
		"decision": FR_ROW_DECISION_PENDING,
		"material_request_type": mr.material_request_type,
	}


@frappe.whitelist()
def get_material_request_details(material_request: str) -> list[dict]:
	"""One row per currency. A list even when there is only one."""
	frappe.has_permission("Material Request", "read", throw=True)
	return fetch_material_request_rows(material_request)


@frappe.whitelist()
def get_unfunded_material_requests(
	company: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
) -> list[dict]:
	frappe.has_permission("Funding Request", "write", throw=True)
	filters: dict = {"docstatus": 1, "status": ["!=", "Stopped"]}
	if company:
		filters["company"] = company
	if from_date and to_date:
		filters["transaction_date"] = ["between", [from_date, to_date]]
	elif from_date:
		filters["transaction_date"] = [">=", from_date]
	elif to_date:
		filters["transaction_date"] = ["<=", to_date]

	filters["material_request_type"] = ["in", list(FUNDING_MATERIAL_REQUEST_TYPES)]
	mr_states = get_material_request_state_names()
	filters[MR_WORKFLOW_STATE_FIELD] = [
		"in",
		[
			pick_workflow_state(mr_states, "Unfunded", default=MR_WORKFLOW_STATE_UNFUNDED),
			pick_workflow_state(
				mr_states,
				MR_WORKFLOW_STATE_SUBMITTED,
				MR_WORKFLOW_STATE_SUBMITTED_LEGACY,
				default=MR_WORKFLOW_STATE_SUBMITTED,
			),
		],
	]
	blocked = set(_material_requests_on_active_funding_requests())
	rows = frappe.get_all(
		"Material Request",
		filters=filters,
		fields=[
			"name",
			"custom_employee",
			"custom_request_description",
			"custom_project",
			"custom_funding_request",
			"transaction_date",
		],
		order_by="transaction_date asc, name asc",
	)
	out = []
	for row in rows:
		if row.name in blocked:
			continue
		if row.custom_funding_request:
			continue
		# One entry per currency, so a mixed request offers both halves.
		out.extend(fetch_material_request_rows(row.name))
	return out


def _material_requests_on_active_funding_requests(exclude_parent: str | None = None) -> list[str]:
	terminal = list(get_funding_workflow_map().terminal_states)
	fr_filters: dict = {}
	if terminal:
		fr_filters["workflow_state"] = ["not in", terminal]
	if exclude_parent:
		fr_filters["name"] = ["!=", exclude_parent]
	parents = frappe.get_all("Funding Request", filters=fr_filters, pluck="name")
	if not parents:
		return []
	return frappe.get_all(
		"Funding Request Material Request",
		filters={"parent": ["in", parents], "material_request": ["is", "set"]},
		pluck="material_request",
	)


@frappe.whitelist()
def make_funding_request(material_request: str):
	"""Open a draft Funding Request with this submitted Material Request already on it."""
	frappe.has_permission("Funding Request", "write", throw=True)
	frappe.has_permission("Material Request", "read", throw=True)
	mr = frappe.get_doc("Material Request", material_request)
	if mr.material_request_type not in FUNDING_MATERIAL_REQUEST_TYPES:
		frappe.throw(
			_("Funding Request is only for Purchase and Operational Expense Material Requests.")
		)
	if mr.docstatus != 1:
		frappe.throw(_("Submit the Material Request before creating a Funding Request."))
	if mr.status == "Stopped":
		frappe.throw(_("Material Request {0} is Stopped.").format(frappe.bold(mr.name)))
	if mr.get("custom_funding_request"):
		frappe.throw(
			_("Material Request {0} is already on Funding Request {1}.").format(
				frappe.bold(mr.name), frappe.bold(mr.custom_funding_request)
			)
		)
	blocked = set(_material_requests_on_active_funding_requests())
	if mr.name in blocked:
		frappe.throw(
			_("Material Request {0} is already on another active Funding Request.").format(
				frappe.bold(mr.name)
			)
		)
	fr = frappe.new_doc("Funding Request")
	fr.company = mr.company
	fr.posting_date = nowdate()
	for details in fetch_material_request_rows(mr.name):
		fr.append("material_requests", details)
	return fr.as_dict()


@frappe.whitelist()
def make_journal_entries(funding_request: str, bank_accounts=None) -> list[str]:
	"""Create one draft Journal Entry per remaining operational-expense row.

	`bank_accounts` maps a currency to the account money leaves, as chosen by
	Finance when they create the entries. A currency left out falls back to the
	company default bank, which only works for the company currency.
	"""
	frappe.has_permission("Journal Entry", "create", throw=True)
	fr = frappe.get_doc("Funding Request", funding_request)
	_assert_funding_request_approved(fr)
	chosen = frappe.parse_json(bank_accounts) if bank_accounts else {}
	if not isinstance(chosen, dict):
		chosen = {}
	created = []
	for row in _outstanding_rows(fr, MATERIAL_REQUEST_TYPE_OPERATIONAL):
		if _open_journal_entry_exists(fr.name, row.material_request, row.get("currency")):
			continue
		je = _build_operational_journal_entry(fr, row, chosen)
		je.insert(ignore_permissions=True)
		created.append(je.name)
	if not created:
		frappe.throw(_("No Journal Entries left to create."))
	sync_funding_request_paid_amounts(fr.name)
	return created


def _draft_journal_entry(funding_request: str, material_request: str, currency: str | None = None) -> str | None:
	"""The unposted entry already raised for this row, if there is one."""
	if not frappe.db.has_column("Journal Entry", "custom_material_request"):
		return None
	drafts = frappe.get_all(
		"Journal Entry",
		filters={
			"custom_funding_request": funding_request,
			"custom_material_request": material_request,
			"docstatus": 0,
		},
		pluck="name",
		order_by="creation asc",
	)
	if drafts and currency:
		drafts = _entries_in_currency(drafts, currency)
	return drafts[0] if drafts else None


def _disbursement_cache_key(kind: str, funding_request: str) -> str:
	return f"cgm_funding_{kind}:{funding_request}:{frappe.session.user}"


@frappe.whitelist()
def set_disbursement_accounts(funding_request: str, bank_accounts=None) -> None:
	"""Hold the bank accounts Finance chose until the Disburse action runs.

	Disburse is a workflow action, and a workflow action carries no input of its
	own. The form asks which account each currency is paid from, parks the answer
	here, and then lets the standard workflow call go ahead; the request picks the
	answer up when its state changes. Kept for ten minutes, for this user only.
	"""
	frappe.has_permission("Funding Request", "write", doc=funding_request, throw=True)
	chosen = frappe.parse_json(bank_accounts) if bank_accounts else {}
	if not isinstance(chosen, dict):
		chosen = {}
	frappe.cache.set_value(_disbursement_cache_key("accounts", funding_request), chosen, expires_in_sec=600)


@frappe.whitelist()
def get_last_disbursement(funding_request: str) -> dict:
	"""What this user's last Disburse created, read once."""
	frappe.has_permission("Funding Request", "read", doc=funding_request, throw=True)
	key = _disbursement_cache_key("posted", funding_request)
	created = frappe.cache.get_value(key) or {}
	frappe.cache.delete_value(key)
	return {
		"journal_entries": created.get("journal_entries") or [],
		"purchase_orders": created.get("purchase_orders") or [],
		"existing_purchase_orders": created.get("existing_purchase_orders") or [],
	}


def disburse_on_workflow_action(funding_request: str) -> dict:
	"""Run the payment for a request that has just been moved to Disbursed."""
	key = _disbursement_cache_key("accounts", funding_request)
	chosen = frappe.cache.get_value(key) or {}
	frappe.cache.delete_value(key)
	result = disburse_funding_request(funding_request, chosen)
	frappe.cache.set_value(
		_disbursement_cache_key("posted", funding_request),
		{
			"journal_entries": result["journal_entries"],
			"purchase_orders": result["purchase_orders"],
			"existing_purchase_orders": result.get("existing_purchase_orders") or [],
		},
		expires_in_sec=600,
	)
	return result


def disburse_funding_request(funding_request: str, bank_accounts=None) -> dict:
	"""Move every approved row still outstanding to its payment document.

	Called by the Disburse workflow action, never directly from the browser: the
	workflow decides who may disburse and from which state.

	The two kinds of row are paid differently, and Disburse does the right thing
	for each rather than asking Finance to know which button goes with which row:

	* **Operational Expense** is paid here. One Journal Entry per row is created
	  and submitted. A draft raised earlier for a row is submitted as it stands,
	  not duplicated.
	* **Purchase / Subcontracting** gets a draft Purchase Order. The money goes
	  out later, against the supplier's invoice, so the request stays in
	  Disbursement in Progress until that payment is recorded.

	All or nothing. If any document cannot be created or posted the error is
	raised and the request is left exactly as it was.
	"""
	fr = frappe.get_doc("Funding Request", funding_request)
	_assert_funding_request_approved(fr)
	chosen = frappe.parse_json(bank_accounts) if bank_accounts else {}
	if not isinstance(chosen, dict):
		chosen = {}

	operational = _outstanding_rows(fr, MATERIAL_REQUEST_TYPE_OPERATIONAL)
	posted = []
	if operational:
		frappe.has_permission("Journal Entry", "create", throw=True)
		frappe.has_permission("Journal Entry", "submit", throw=True)
	for row in operational:
		draft = _draft_journal_entry(fr.name, row.material_request, row.get("currency"))
		if draft:
			je = frappe.get_doc("Journal Entry", draft)
		else:
			je = _build_operational_journal_entry(fr, row, chosen)
			je.insert(ignore_permissions=True)
		je.submit()
		posted.append(je.name)

	orders, open_orders = [], []
	if _outstanding_rows(fr, None, purchase=True):
		frappe.has_permission("Purchase Order", "create", throw=True)
		orders, open_orders = _raise_purchase_orders(fr)

	# An order that already exists is still progress: it is tied to this request
	# and the request moves on, so Finance is taken to the order rather than told
	# there is nothing to do. Only a request with no unpaid row at all is refused.
	if not posted and not orders and not open_orders:
		frappe.throw(_("Nothing left to disburse on {0}: every approved row is paid.").format(frappe.bold(fr.name)))
	sync_funding_request_paid_amounts(fr.name)
	return {
		"journal_entries": posted,
		"purchase_orders": orders,
		"existing_purchase_orders": open_orders,
		"workflow_state": frappe.db.get_value("Funding Request", fr.name, "workflow_state"),
	}


def _adopt_purchase_order(purchase_order: str, funding_request: str) -> None:
	"""Tie an order raised before the Funding Request existed to that request.

	A Purchase Order made straight from the Material Request carries no link to
	the Funding Request that later funds it. Without the link the request's
	Connections show no order, and Finance has no way to get from the request to
	the document the payment now depends on.
	"""
	if not frappe.get_meta("Purchase Order").has_field("custom_funding_request"):
		return
	if frappe.db.get_value("Purchase Order", purchase_order, "custom_funding_request"):
		return
	frappe.db.set_value(
		"Purchase Order", purchase_order, "custom_funding_request", funding_request, update_modified=False
	)


def adopt_open_purchase_orders(fr) -> list[str]:
	"""Tie orders that already exist for this request's approved Purchase rows to it.

	Purchase does not wait on funding, so an order is often raised from the
	Material Request before the Funding Request exists. Once the request is
	approved that order is the request's payment document, and the request has to
	know about it: otherwise it sits in Approved offering to create an order that
	is already there, and cancelling the request leaves the order behind.
	"""
	adopted = []
	for row in _outstanding_rows(fr, None, purchase=True):
		order = _open_purchase_order_name(row.material_request)
		if order and order not in adopted:
			_adopt_purchase_order(order, fr.name)
			adopted.append(order)
	return adopted


def _raise_purchase_orders(fr) -> tuple[list[str], list[str]]:
	"""Draft Purchase Orders for purchase rows that have none. Returns (created, already open)."""
	created = []
	existing = []
	for row in _outstanding_rows(fr, None, purchase=True):
		if _open_purchase_order_exists(row.material_request):
			po_name = _open_purchase_order_name(row.material_request)
			if po_name and po_name not in existing:
				existing.append(po_name)
				_adopt_purchase_order(po_name, fr.name)
			continue
		po = make_purchase_order(row.material_request)
		if isinstance(po, dict):
			po = frappe.get_doc(po)
		_ensure_purchase_order_required_by(po)
		if po.meta.has_field("custom_funding_request"):
			po.custom_funding_request = fr.name
		po.insert(ignore_permissions=True, ignore_mandatory=True)
		created.append(po.name)
	return created, existing


@frappe.whitelist()
def make_purchase_orders(funding_request: str) -> list[str]:
	"""Create one draft Purchase Order per remaining purchase row."""
	frappe.has_permission("Purchase Order", "create", throw=True)
	fr = frappe.get_doc("Funding Request", funding_request)
	_assert_funding_request_approved(fr)
	created, skipped = _raise_purchase_orders(fr)
	if not created:
		if skipped:
			frappe.throw(
				_("Draft Purchase Order(s) already exist: {0}. Open them to continue procurement.").format(
					", ".join(skipped)
				)
			)
		frappe.throw(_("No Purchase Orders left to create."))
	sync_funding_request_paid_amounts(fr.name)
	return created


def _assert_funding_request_approved(fr) -> None:
	if cint_docstatus(fr.docstatus) != 1:
		frappe.throw(
			_("Submit Funding Request {0} before creating payment documents.").format(
				frappe.bold(fr.name)
			)
		)
	if not funding_is_approved(fr.workflow_state, fr.docstatus):
		frappe.throw(
			_("Cannot create payment documents before approval of {0}.").format(
				frappe.bold(fr.name)
			)
		)
	if get_funding_workflow_map().is_fully_complete(fr.workflow_state):
		frappe.throw(
			_("{0} is {1}. Nothing more can be paid against it.").format(
				frappe.bold(fr.name), frappe.bold(fr.workflow_state)
			)
		)


def _build_operational_journal_entry(fr, row, bank_accounts: dict | None = None):
	"""One draft entry: expense debited, bank credited, in the row's currency.

	The amount outstanding is held in the row's own currency. The rate is fetched
	live for the posting date rather than taken from the request, because the
	estimate on the request was made for the approver's benefit and may be weeks
	old by the time Finance pays. Where the live rate cannot be had, the request
	estimate is used as a fallback and named in the entry's remark, so nobody has
	to guess which rate a posted entry used.
	"""
	remaining = flt(row.approved_amount) - flt(row.funded_amount)
	if remaining <= 0:
		frappe.throw(_("No remaining approved amount to journal."))
	expense_account = _material_request_expense_account(
		row.material_request, fr.company, row.get("currency")
	)
	if not expense_account:
		frappe.throw(
			_(
				"Set Expense Account on Material Request {0} items, or configure "
				"Default Operational Expense Account in CGM Shipping Settings."
			).format(frappe.bold(row.material_request))
		)
	base = company_currency(fr.company)
	row_currency = row.get("currency") or base
	posting_date = nowdate()
	rate, rate_note = _payment_exchange_rate(row, row_currency, base, posting_date)
	bank_account = _resolve_bank_account(fr.company, row_currency, base, bank_accounts)
	remark = " - ".join(
		part
		for part in (
			row.employee_name or row.employee,
			get_material_request_item_summary(row.material_request),
			row.material_request,
			fr.name,
			rate_note,
		)
		if part
	)
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = fr.company
	je.posting_date = posting_date
	je.user_remark = remark
	if je.meta.has_field("custom_funding_request"):
		je.custom_funding_request = fr.name
	if je.meta.has_field("custom_material_request"):
		je.custom_material_request = row.material_request
	if je.meta.has_field("custom_project"):
		je.custom_project = row.project
	if je.meta.has_field("custom_employee"):
		je.custom_employee = row.employee
	cost_center = frappe.db.get_value("Company", fr.company, "cost_center")
	base_amount = flt(flt(remaining) * flt(rate), 2)
	if row_currency != base:
		je.multi_currency = 1
	debit = _journal_line(expense_account, "debit", remaining, base_amount, row_currency, base, rate, remark)
	credit = _journal_line(bank_account, "credit", remaining, base_amount, row_currency, base, rate, remark)
	if row.project:
		debit["project"] = row.project
		credit["project"] = row.project
	if cost_center:
		debit["cost_center"] = cost_center
		credit["cost_center"] = cost_center
	je.append("accounts", debit)
	je.append("accounts", credit)
	return je


def _payment_exchange_rate(row, row_currency: str, base: str, posting_date: str) -> tuple[float, str]:
	"""Today's rate, with the request's estimate as a named fallback."""
	if row_currency == base:
		return 1.0, ""
	rate = live_exchange_rate(row_currency, base, posting_date)
	if rate > 0:
		return rate, _("rate {0} {1}/{2} on {3}").format(rate, row_currency, base, posting_date)
	estimate = flt(row.get("exchange_rate"))
	if estimate > 0:
		return estimate, _("estimated rate {0} {1}/{2} (live rate unavailable)").format(
			estimate, row_currency, base
		)
	frappe.throw(
		_(
			"Could not fetch an exchange rate for {0} to {1}, and Material Request {2} "
			"carries no estimate. Add a Currency Exchange record for {3} or set an "
			"Exchange Rate on the request before creating the Journal Entry."
		).format(
			frappe.bold(row_currency),
			frappe.bold(base),
			frappe.bold(row.material_request),
			posting_date,
		)
	)


def _journal_line(
	account: str,
	side: str,
	foreign_amount: float,
	base_amount: float,
	row_currency: str,
	base: str,
	rate: float,
	remark: str,
) -> dict:
	"""One Journal Entry Account row, stated in whichever currency the account holds.

	A line is written in the account's own currency, not the row's. That is what
	lets a USD expense be settled from a KES bank account, or the reverse: both
	lines still carry the same company-currency figure, so the entry balances
	whatever mix of accounts is used.
	"""
	account_currency = frappe.db.get_value("Account", account, "account_currency") or base
	if account_currency == base:
		amount, line_rate = base_amount, 1.0
	elif account_currency == row_currency:
		amount, line_rate = foreign_amount, rate
	else:
		frappe.throw(
			_(
				"Account {0} is held in {1}, which is neither the request currency "
				"({2}) nor the company currency ({3}). Choose an account in one of "
				"those two currencies."
			).format(
				frappe.bold(account), frappe.bold(account_currency),
				frappe.bold(row_currency), frappe.bold(base),
			)
		)
	return {
		"account": account,
		"account_currency": account_currency,
		"exchange_rate": line_rate,
		f"{side}_in_account_currency": amount,
		"user_remark": remark,
	}


def _resolve_bank_account(
	company: str, row_currency: str, base: str, bank_accounts: dict | None
) -> str:
	"""The account money leaves, as picked by Finance, validated before it is used.

	Finance chooses this when they create the entries rather than it being
	configured once, because which account a payment leaves is a treasury decision
	taken per payment, not a fixed property of a currency.
	"""
	chosen = (bank_accounts or {}).get(row_currency) or (bank_accounts or {}).get("*")
	if not chosen:
		chosen = _company_bank_or_cash_account(company)
		if not chosen:
			frappe.throw(
				_(
					"Choose a bank account for {0}, or set a Default Bank Account on "
					"Company {1}."
				).format(frappe.bold(row_currency), frappe.bold(company))
			)
	account = frappe.db.get_value(
		"Account",
		chosen,
		["name", "company", "is_group", "account_type", "account_currency"],
		as_dict=True,
	)
	if not account:
		frappe.throw(_("Bank account {0} does not exist.").format(frappe.bold(chosen)))
	if account.company != company:
		frappe.throw(
			_("Bank account {0} belongs to {1}, not {2}.").format(
				frappe.bold(chosen), frappe.bold(account.company), frappe.bold(company)
			)
		)
	if cint(account.is_group):
		frappe.throw(_("{0} is a group account, so it cannot be paid from.").format(frappe.bold(chosen)))
	if account.account_type not in ("Bank", "Cash"):
		frappe.throw(
			_("{0} is a {1} account. Choose a Bank or Cash account to pay from.").format(
				frappe.bold(chosen), frappe.bold(account.account_type or _("non-bank"))
			)
		)
	currency = account.account_currency or base
	if currency not in (row_currency, base):
		frappe.throw(
			_(
				"{0} is held in {1}, so it cannot settle a {2} request. Choose an "
				"account in {2} or {3}."
			).format(
				frappe.bold(chosen), frappe.bold(currency),
				frappe.bold(row_currency), frappe.bold(base),
			)
		)
	return account.name


def _material_request_expense_account(
	material_request: str, company: str | None, currency: str | None = None
) -> str | None:
	"""The account to debit, taken from a line in the currency being paid.

	The account belongs to the line, not to the request: it is whatever the
	requester chose, or what Item Defaults filled in. On a request holding both
	KES and USD lines the two halves usually post to different accounts, so taking
	the first line's account would send the USD payment to wherever the KES line
	happened to point.

	Falls back to any priced line, then to the Settings default, so a request whose
	lines carry no account still produces an entry rather than failing.
	"""
	rows = frappe.get_all(
		"Material Request Item",
		filters={"parent": material_request},
		fields=["expense_account", "custom_currency", "amount"],
		order_by="idx",
	)

	def usable(account):
		return account and not cint(frappe.db.get_value("Account", account, "is_group"))

	if currency:
		base = company_currency(company)
		for row in rows:
			if (row.custom_currency or base) == currency and usable(row.expense_account):
				return row.expense_account

	for row in rows:
		if usable(row.expense_account):
			return row.expense_account
	return _default_operational_expense_account(company)


def _default_operational_expense_account(company: str | None) -> str | None:
	if not company or not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return None
	# CGM Shipping Settings is a Single, so it has no table of its own and
	# `frappe.db.has_column` raises instead of returning False. Reaching this with
	# a raw ProgrammingError lost the clear "set an expense account" message that
	# the caller raises when nothing is configured.
	if not frappe.get_meta("CGM Shipping Settings").has_field(
		"default_operational_expense_account"
	):
		return None
	account = frappe.db.get_single_value("CGM Shipping Settings", "default_operational_expense_account")
	if account and not cint(frappe.db.get_value("Account", account, "is_group")):
		return account
	return None


def _company_bank_or_cash_account(company: str | None) -> str | None:
	if not company:
		return None
	return frappe.db.get_value("Company", company, "default_bank_account") or frappe.db.get_value(
		"Company", company, "default_cash_account"
	)


def _outstanding_rows(fr, request_type: str | None, purchase: bool = False):
	out = []
	for row in fr.material_requests:
		if not row.material_request:
			continue
		if getattr(row, "decision", None) != FR_ROW_DECISION_APPROVED:
			continue
		if flt(row.approved_amount) - flt(row.funded_amount) <= 0:
			continue
		mr_type = frappe.db.get_value(
			"Material Request", row.material_request, "material_request_type"
		)
		if purchase and mr_type in PURCHASE_REQUEST_TYPES:
			out.append(row)
		elif request_type and mr_type == request_type:
			out.append(row)
	return out


def _open_journal_entry_exists(
	funding_request: str, material_request: str, currency: str | None = None
) -> bool:
	"""Is there already an entry for this request *in this currency*?

	A mixed request has one row and one entry per currency, so keying on the
	request alone would create the first entry and then decide the second was a
	duplicate.
	"""
	if not frappe.db.has_column("Journal Entry", "custom_material_request"):
		return False
	entries = frappe.get_all(
		"Journal Entry",
		filters={
			"custom_funding_request": funding_request,
			"custom_material_request": material_request,
			"docstatus": ["<", 2],
		},
		pluck="name",
	)
	if not entries:
		return False
	if not currency:
		return True
	return bool(_entries_in_currency(entries, currency))


def _entries_in_currency(entries: list[str], currency: str) -> list[str]:
	"""Those entries whose debit line is written in this currency.

	A company-currency entry carries no foreign line, so it is matched by its own
	currency on the debit side.
	"""
	if not entries:
		return []
	rows = frappe.db.sql(
		"""
		select distinct jea.parent
		from `tabJournal Entry Account` jea
		where jea.parent in %(entries)s
			and jea.debit_in_account_currency > 0
			and jea.account_currency = %(currency)s
		""",
		{"entries": entries, "currency": currency},
	)
	return [r[0] for r in rows]


def _open_purchase_order_exists(material_request: str) -> bool:
	return bool(_open_purchase_order_name(material_request))


def _open_purchase_order_name(material_request: str) -> str | None:
	return frappe.db.get_value(
		"Purchase Order Item",
		{"material_request": material_request, "docstatus": ["<", 2]},
		"parent",
	)


@frappe.whitelist()
def get_funding_pay_options(funding_request: str) -> dict:
	"""Outstanding rows for Finance, split by how they are paid."""
	frappe.has_permission("Funding Request", "read", throw=True)
	fr = frappe.get_doc("Funding Request", funding_request)
	base = company_currency(fr.company)
	# A closed request offers nothing, whatever its rows say.
	if not funding_is_approved(fr.workflow_state, fr.docstatus) or get_funding_workflow_map().is_fully_complete(
		fr.workflow_state
	):
		return {"operational": [], "purchase": [], "company_currency": base, "currencies": []}
	operational = []
	purchase = []
	for row in fr.material_requests:
		if not row.material_request:
			continue
		if getattr(row, "decision", None) != FR_ROW_DECISION_APPROVED:
			continue
		remaining = flt(row.approved_amount) - flt(row.funded_amount)
		if remaining <= 0:
			continue
		mr_type = frappe.db.get_value(
			"Material Request", row.material_request, "material_request_type"
		)
		payload = {
			"material_request": row.material_request,
			"employee": row.employee,
			"employee_name": row.employee_name,
			"item_summary": row.item_summary,
			"remaining": remaining,
			"approved_amount": flt(row.approved_amount),
			"funded_amount": flt(row.funded_amount),
			"currency": row.get("currency") or base,
			"material_request_type": mr_type,
			"label": _pay_option_label(row, remaining),
		}
		if mr_type == MATERIAL_REQUEST_TYPE_OPERATIONAL:
			# A row with a draft entry is still unpaid, so it is still offered:
			# Disburse posts that draft. It needs no bank account, the draft has one.
			payload["draft_entry"] = _draft_journal_entry(fr.name, row.material_request, row.get("currency"))
			operational.append(payload)
		elif mr_type in PURCHASE_REQUEST_TYPES:
			# Offered even when its order already exists: Disburse then ties that
			# order to this request and moves the request on.
			payload["existing_order"] = _open_purchase_order_name(row.material_request)
			purchase.append(payload)
	# Finance picks one bank account per currency about to be paid, so the dialog
	# needs to know which currencies are actually on the request.
	currencies = []
	for payload in operational:
		if payload.get("draft_entry"):
			continue
		if payload["currency"] not in currencies:
			currencies.append(payload["currency"])
	return {
		"operational": operational,
		"purchase": purchase,
		"company_currency": base,
		"currencies": sorted(currencies, key=lambda c: (c != base, c)),
		"default_bank_account": _company_bank_or_cash_account(fr.company),
	}


def _pay_option_label(row, remaining) -> str:
	who = row.employee_name or row.employee or row.material_request
	what = row.item_summary or row.material_request
	currency = row.get("currency")
	amount = f"{currency} {flt(remaining):,.2f}" if currency else f"{flt(remaining):,.2f}"
	return f"{who} - {what} - {amount}"


# ── Project dashboard ────────────────────────────────────────────────────────


def get_project_dashboard_data(data):
	"""Surface requisition, funding, and actual accounting docs on the shipment."""
	transactions = data.setdefault("transactions", [])
	labels = {group.get("label") for group in transactions}
	if _("Funding") not in labels and "Funding" not in labels:
		transactions.append(
			{
				"label": _("Funding"),
				"items": ["Journal Entry"],
			}
		)
	for group in transactions:
		if group.get("label") in (_("Purchase"), "Purchase"):
			items = group.setdefault("items", [])
			if "Payment Entry" not in items:
				items.append("Payment Entry")
	if _("Portal") not in labels and "Portal" not in labels:
		transactions.append(
			{
				"label": _("Portal"),
				"items": ["Shipment Update", "Portal Feedback"],
			}
		)
	non_standard = data.setdefault("non_standard_fieldnames", {})
	non_standard["Material Request"] = "custom_project"
	non_standard["Journal Entry"] = "custom_project"
	return data


def get_material_request_dashboard_data(data):
	transactions = data.setdefault("transactions", [])
	transactions.append(
		{"label": _("Funding"), "items": ["Funding Request", "Journal Entry"]}
	)
	non_standard = data.setdefault("non_standard_fieldnames", {})
	non_standard["Journal Entry"] = "custom_material_request"
	internal = data.setdefault("internal_links", {})
	internal["Funding Request"] = "custom_funding_request"
	return data
