"""Material Request funding workflow: Purpose, Project carry-through, Funding Request.

ERPNext already owns Material Request, purchasing, stock, Journal Entry, and
Payment Entry. Operational Expense is paid by Journal Entry (expense + bank).
Purchase still uses Purchase Order. Employee Advance is not used for funding.
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
	MR_WORKFLOW_STATE_UNFUNDED,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.funding_workflow import (
	get_funding_workflow_map,
	get_material_request_state_names,
	pick_workflow_state,
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
			fr_workflow_state,
			*wf.pending_states,
			"Pending",
			"Pending Approval",
			default=fr_workflow_state or "Pending",
		)
	if wf.is_disbursed(fr_workflow_state) or wf.is_completed(fr_workflow_state):
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
	fr_workflow_state: str | None, approved_amount, funded_amount, workflow=None, mr_workflow=None
) -> str:
	"""Operational Expense completes per request when that request is paid, not via PO."""
	mr_states = get_material_request_state_names(mr_workflow)
	state = mr_workflow_state_from_funding_request(
		fr_workflow_state, workflow=workflow, mr_workflow=mr_workflow
	)
	approved = pick_workflow_state(mr_states, "Approved", default=MR_WORKFLOW_STATE_APPROVED)
	disbursed = pick_workflow_state(mr_states, "Disbursed", default=MR_WORKFLOW_STATE_DISBURSED)
	if (
		state == approved
		and flt(approved_amount) > 0
		and flt(funded_amount) + 0.005 >= flt(approved_amount)
	):
		return disbursed
	return state


def released_mr_workflow_state(material_request: str, mr_workflow=None) -> str:
	"""State to restore on a Material Request when it leaves a Funding Request."""
	mr_states = get_material_request_state_names(mr_workflow)
	mr_type = frappe.db.get_value("Material Request", material_request, "material_request_type")
	if mr_type == MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return pick_workflow_state(mr_states, "Unfunded", default=MR_WORKFLOW_STATE_UNFUNDED)
	return pick_workflow_state(mr_states, "Submitted", default=MR_WORKFLOW_STATE_SUBMITTED)


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
	current: str | None, total_funded: float, total_approved: float, workflow=None
) -> str | None:
	"""Payment-driven Funding Request state.

	Creating a draft Journal Entry is not payment, so paid can stay 0.
	Never reverse Disbursement in Progress back to Approved — that transition
	is not in the workflow.
	"""
	wf = get_funding_workflow_map(workflow)
	if current not in wf.progress_states():
		return current
	funded = flt(total_funded)
	approved = flt(total_approved)
	disbursed = next(iter(wf.complete_from_states), None)
	if approved > 0 and funded + 0.005 >= approved:
		return disbursed or current
	if funded > 0:
		return wf.disbursement_state or current
	if wf.is_disbursed(current):
		return wf.disbursement_state or current
	return current


PURCHASE_REQUEST_TYPES_REQUIRING_FUNDING = frozenset({"Purchase", "Subcontracting"})


def material_request_purchase_is_funding_approved(material_request: str) -> bool:
	"""Purchase/Subcontracting may create a PO only after approved funding."""
	if not material_request:
		return True
	mr = frappe.db.get_value(
		"Material Request",
		material_request,
		["material_request_type", "custom_funding_request"],
		as_dict=True,
	)
	if not mr or mr.material_request_type not in PURCHASE_REQUEST_TYPES_REQUIRING_FUNDING:
		return True
	if not mr.custom_funding_request:
		return False
	fr = frappe.db.get_value(
		"Funding Request",
		mr.custom_funding_request,
		["workflow_state", "docstatus"],
		as_dict=True,
	)
	return bool(fr and funding_is_approved(fr.workflow_state, fr.docstatus))


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


def get_material_request_requested_amount(material_request) -> float:
	"""Alias kept for Funding Request callers. Always the Items total."""
	return get_material_request_total(material_request)


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
		return " — ".join(parts)
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


def before_material_request_validate(doc, method=None) -> None:
	_ensure_operational_expense_item_descriptions(doc)


def on_material_request_validate(doc, method=None) -> None:
	_set_requester_defaults(doc)
	_copy_header_project_to_items(doc)
	_clear_warehouse_for_operational_expense(doc)
	_set_default_funding_workflow_state(doc)
	_validate_operational_expense_request(doc)


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
		else pick_workflow_state(mr_states, "Submitted", default=MR_WORKFLOW_STATE_SUBMITTED)
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
	for item in doc.get("items") or []:
		if not strip_html((item.get("description") or "").strip()):
			frappe.throw(
				_("Row {0}: add a Description on the item — this is the note Finance and the Funding Approver see.").format(
					item.idx
				)
			)
			break


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


def _ensure_operational_expense_item_descriptions(doc) -> None:
	if doc.get("material_request_type") != MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return
	for item in doc.get("items") or []:
		if strip_html((item.get("description") or "").strip()):
			continue
		fallback = (item.get("item_name") or item.get("item_code") or "").strip()
		if fallback:
			item.description = fallback


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


def on_journal_entry_on_cancel(doc, method=None) -> None:
	sync_funding_request_paid_amounts(doc.get("custom_funding_request"))


def sync_funding_requests_touched_by_payment_entry(doc) -> None:
	"""Purchase Invoice payments only — Operational Expense is paid via Journal Entry."""
	seen = set()
	for ref in doc.get("references") or []:
		fr_name = None
		if ref.reference_doctype == "Purchase Invoice" and ref.reference_name:
			fr_name = _funding_request_from_purchase_invoice(ref.reference_name)
		if fr_name and fr_name not in seen:
			seen.add(fr_name)
			sync_funding_request_paid_amounts(fr_name)


def sync_funding_request_paid_amounts(funding_request: str | None) -> None:
	"""Funded Amount is cash actually paid, not draft Journal Entries or POs."""
	if not funding_request or not frappe.db.exists("Funding Request", funding_request):
		return
	fr = frappe.get_doc("Funding Request", funding_request)
	changed = False
	for row in fr.material_requests:
		if not row.material_request:
			continue
		paid = paid_amount_for_material_request(fr.name, row.material_request)
		if abs(flt(row.funded_amount) - flt(paid)) > 0.005:
			row.funded_amount = paid
			changed = True
	fr.calculate_totals()
	next_state = funding_progress_state(
		fr.workflow_state, fr.total_funded, fr.total_approved
	)
	state_changed = next_state != fr.workflow_state
	if not changed and not state_changed:
		return
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
	fr.sync_material_request_links()


def paid_amount_for_material_request(funding_request: str, material_request: str) -> float:
	mr_type = frappe.db.get_value("Material Request", material_request, "material_request_type")
	if mr_type == MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return _paid_against_journal_entries(funding_request, material_request)
	if mr_type in PURCHASE_REQUEST_TYPES_REQUIRING_FUNDING:
		return _paid_against_purchase_orders(material_request)
	return 0.0


def _paid_against_journal_entries(funding_request: str, material_request: str) -> float:
	if not frappe.db.has_column("Journal Entry", "custom_material_request"):
		return 0.0
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
		return 0.0
	paid = frappe.db.sql(
		"""
		select coalesce(sum(jea.debit_in_account_currency), 0)
		from `tabJournal Entry Account` jea
		inner join `tabJournal Entry` je on je.name = jea.parent
		where je.docstatus = 1
			and je.name in %(entries)s
			and jea.debit_in_account_currency > 0
		""",
		{"entries": entries},
	)
	return flt(paid[0][0] if paid else 0)


def _paid_against_purchase_orders(material_request: str) -> float:
	purchase_orders = frappe.get_all(
		"Purchase Order Item",
		filters={"material_request": material_request, "docstatus": 1},
		pluck="parent",
	)
	if not purchase_orders:
		return 0.0
	paid = frappe.db.sql(
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
		{"purchase_orders": list(set(purchase_orders))},
	)
	return flt(paid[0][0] if paid else 0)


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
		"variance": 0,
		"funded_amount": 0,
		"status": pick_workflow_state(
			get_material_request_state_names(),
			"On Funding Request",
			default=MR_WORKFLOW_STATE_ON_FUNDING_REQUEST,
		),
		"decision": FR_ROW_DECISION_PENDING,
		"material_request_type": mr.material_request_type,
	}


@frappe.whitelist()
def get_material_request_details(material_request: str) -> dict:
	frappe.has_permission("Material Request", "read", throw=True)
	return fetch_material_request_details(material_request)


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

	mr_states = get_material_request_state_names()
	filters[MR_WORKFLOW_STATE_FIELD] = [
		"in",
		[
			pick_workflow_state(mr_states, "Unfunded", default=MR_WORKFLOW_STATE_UNFUNDED),
			pick_workflow_state(mr_states, "Submitted", default=MR_WORKFLOW_STATE_SUBMITTED),
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
		details = fetch_material_request_details(row.name)
		out.append(details)
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
	fr.append("material_requests", fetch_material_request_details(mr.name))
	return fr.as_dict()


@frappe.whitelist()
def make_journal_entries(funding_request: str) -> list[str]:
	"""Create one draft Journal Entry per remaining operational-expense row."""
	frappe.has_permission("Journal Entry", "create", throw=True)
	fr = frappe.get_doc("Funding Request", funding_request)
	_assert_funding_request_approved(fr)
	created = []
	for row in _outstanding_rows(fr, MATERIAL_REQUEST_TYPE_OPERATIONAL):
		if _open_journal_entry_exists(fr.name, row.material_request):
			continue
		je = _build_operational_journal_entry(fr, row)
		je.insert(ignore_permissions=True)
		created.append(je.name)
	if not created:
		frappe.throw(_("No Journal Entries left to create."))
	return created


@frappe.whitelist()
def make_purchase_orders(funding_request: str) -> list[str]:
	"""Create one draft Purchase Order per remaining purchase row."""
	frappe.has_permission("Purchase Order", "create", throw=True)
	fr = frappe.get_doc("Funding Request", funding_request)
	_assert_funding_request_approved(fr)
	created = []
	for row in _outstanding_rows(fr, None, purchase=True):
		if _open_purchase_order_exists(row.material_request):
			continue
		po = make_purchase_order(row.material_request)
		if isinstance(po, dict):
			po = frappe.get_doc(po)
		_ensure_purchase_order_required_by(po)
		if po.meta.has_field("custom_funding_request"):
			po.custom_funding_request = fr.name
		po.insert(ignore_permissions=True, ignore_mandatory=True)
		created.append(po.name)
	if not created:
		frappe.throw(_("No Purchase Orders left to create."))
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


def _build_operational_journal_entry(fr, row):
	remaining = flt(row.approved_amount) - flt(row.funded_amount)
	if remaining <= 0:
		frappe.throw(_("No remaining approved amount to journal."))
	expense_account = _material_request_expense_account(row.material_request, fr.company)
	if not expense_account:
		frappe.throw(
			_(
				"Set Expense Account on Material Request {0} items, or configure "
				"Default Operational Expense Account in CGM Shipping Settings."
			).format(frappe.bold(row.material_request))
		)
	bank_account = _company_bank_or_cash_account(fr.company)
	if not bank_account:
		frappe.throw(
			_("Set Default Bank Account on Company {0} before creating the Journal Entry.").format(
				frappe.bold(fr.company)
			)
		)
	remark = " — ".join(
		part
		for part in (
			row.employee_name or row.employee,
			get_material_request_item_summary(row.material_request),
			row.material_request,
			fr.name,
		)
		if part
	)
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = fr.company
	je.posting_date = nowdate()
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
	debit = {
		"account": expense_account,
		"debit_in_account_currency": remaining,
		"user_remark": remark,
	}
	credit = {
		"account": bank_account,
		"credit_in_account_currency": remaining,
		"user_remark": remark,
	}
	if row.project:
		debit["project"] = row.project
		credit["project"] = row.project
	if cost_center:
		debit["cost_center"] = cost_center
		credit["cost_center"] = cost_center
	je.append("accounts", debit)
	je.append("accounts", credit)
	return je


def _material_request_expense_account(material_request: str, company: str | None) -> str | None:
	for account in frappe.get_all(
		"Material Request Item",
		filters={"parent": material_request},
		pluck="expense_account",
		order_by="idx",
	):
		if account and not cint(frappe.db.get_value("Account", account, "is_group")):
			return account
	return _default_operational_expense_account(company)


def _default_operational_expense_account(company: str | None) -> str | None:
	if not company or not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return None
	if not frappe.db.has_column("CGM Shipping Settings", "default_operational_expense_account"):
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
		if purchase and mr_type in PURCHASE_REQUEST_TYPES_REQUIRING_FUNDING:
			out.append(row)
		elif request_type and mr_type == request_type:
			out.append(row)
	return out


def _open_journal_entry_exists(funding_request: str, material_request: str) -> bool:
	if not frappe.db.has_column("Journal Entry", "custom_material_request"):
		return False
	return bool(
		frappe.db.exists(
			"Journal Entry",
			{
				"custom_funding_request": funding_request,
				"custom_material_request": material_request,
				"docstatus": ["<", 2],
			},
		)
	)


def _open_purchase_order_exists(material_request: str) -> bool:
	return bool(
		frappe.db.exists(
			"Purchase Order Item",
			{"material_request": material_request, "docstatus": ["<", 2]},
		)
	)


@frappe.whitelist()
def get_funding_pay_options(funding_request: str) -> dict:
	"""Outstanding rows for Finance, split by how they are paid."""
	frappe.has_permission("Funding Request", "read", throw=True)
	fr = frappe.get_doc("Funding Request", funding_request)
	if not funding_is_approved(fr.workflow_state, fr.docstatus):
		return {"operational": [], "purchase": []}
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
			"material_request_type": mr_type,
			"label": _pay_option_label(row, remaining),
		}
		if mr_type == MATERIAL_REQUEST_TYPE_OPERATIONAL:
			if not _open_journal_entry_exists(fr.name, row.material_request):
				operational.append(payload)
		elif mr_type in PURCHASE_REQUEST_TYPES_REQUIRING_FUNDING:
			if not _open_purchase_order_exists(row.material_request):
				purchase.append(payload)
	return {"operational": operational, "purchase": purchase}


def _pay_option_label(row, remaining) -> str:
	who = row.employee_name or row.employee or row.material_request
	what = row.item_summary or row.material_request
	return f"{who} — {what} — {flt(remaining):,.2f}"


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

