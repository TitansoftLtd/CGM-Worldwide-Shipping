"""Material Request funding workflow: Purpose, Project carry-through, Funding Request.

ERPNext already owns Material Request, purchasing, stock, Employee Advance, and
Payment Entry. This module only connects those documents for CGM requisition
funding. It does not replace accounting vouchers.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	DIRECTOR_ROLE,
	FUNDING_REQUEST_ACTION_APPROVE,
	FUNDING_REQUEST_ACTION_CANCEL,
	FUNDING_REQUEST_ACTION_COMPLETE,
	FUNDING_REQUEST_ACTION_MARK_FUNDED,
	FUNDING_REQUEST_ACTION_REJECT,
	FUNDING_REQUEST_ACTION_START_FUNDING,
	FUNDING_REQUEST_ACTION_SUBMIT,
	FUNDING_REQUEST_APPROVED_STATES,
	FUNDING_REQUEST_STATE_APPROVED,
	FUNDING_REQUEST_STATE_CANCELLED,
	FUNDING_REQUEST_STATE_COMPLETED,
	FUNDING_REQUEST_STATE_DRAFT,
	FUNDING_REQUEST_STATE_FUNDED,
	FUNDING_REQUEST_STATE_FUNDING,
	FUNDING_REQUEST_STATE_PENDING,
	FUNDING_REQUEST_STATE_REJECTED,
	FUNDING_REQUEST_WORKFLOW_NAME,
	MATERIAL_REQUEST_TYPE_OPERATIONAL,
	MR_FUNDING_ACTION_CANCEL,
	MR_FUNDING_ACTION_SUBMIT,
	MR_FUNDING_ACTION_SUBMIT_REQUEST,
	MR_FUNDING_STATE_APPROVED,
	MR_FUNDING_STATE_CANCELLED,
	MR_FUNDING_STATE_DRAFT,
	MR_FUNDING_STATE_FUNDED,
	MR_FUNDING_STATE_ON_REQUEST,
	MR_FUNDING_STATE_PENDING,
	MR_FUNDING_STATE_REJECTED,
	MR_FUNDING_STATE_SUBMITTED,
	MR_FUNDING_STATE_UNFUNDED,
	MR_FUNDING_WORKFLOW_NAME,
	MR_FUNDING_WORKFLOW_STATE_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _ensure_cf, _upsert_cf

MODULE = "CGM Worldwide Shipping"

INACTIVE_FUNDING_STATES = frozenset(
	{FUNDING_REQUEST_STATE_REJECTED, FUNDING_REQUEST_STATE_CANCELLED}
)

OE_WORKFLOW_CONDITION = f'doc.material_request_type=="{MATERIAL_REQUEST_TYPE_OPERATIONAL}"'
NON_OE_WORKFLOW_CONDITION = f'doc.material_request_type!="{MATERIAL_REQUEST_TYPE_OPERATIONAL}"'


def mr_funding_state_for_funding_request(workflow_state: str | None) -> str:
	"""Map Funding Request workflow_state → Material Request funding Workflow State."""
	return {
		FUNDING_REQUEST_STATE_DRAFT: MR_FUNDING_STATE_ON_REQUEST,
		FUNDING_REQUEST_STATE_PENDING: MR_FUNDING_STATE_PENDING,
		FUNDING_REQUEST_STATE_APPROVED: MR_FUNDING_STATE_APPROVED,
		FUNDING_REQUEST_STATE_FUNDING: MR_FUNDING_STATE_APPROVED,
		FUNDING_REQUEST_STATE_FUNDED: MR_FUNDING_STATE_FUNDED,
		FUNDING_REQUEST_STATE_COMPLETED: MR_FUNDING_STATE_FUNDED,
		FUNDING_REQUEST_STATE_REJECTED: MR_FUNDING_STATE_REJECTED,
	}.get(workflow_state or "", MR_FUNDING_STATE_ON_REQUEST)


def mr_row_funding_state(
	fr_workflow_state: str | None, approved_amount, funded_amount
) -> str:
	"""Operational Expense completes per request when that request is paid, not via PO."""
	state = mr_funding_state_for_funding_request(fr_workflow_state)
	if (
		state == MR_FUNDING_STATE_APPROVED
		and flt(approved_amount) > 0
		and flt(funded_amount) + 0.005 >= flt(approved_amount)
	):
		return MR_FUNDING_STATE_FUNDED
	return state


def released_mr_funding_state(material_request: str) -> str:
	"""State to restore on a Material Request when it leaves a Funding Request."""
	mr_type = frappe.db.get_value("Material Request", material_request, "material_request_type")
	if mr_type == MATERIAL_REQUEST_TYPE_OPERATIONAL:
		return MR_FUNDING_STATE_UNFUNDED
	return MR_FUNDING_STATE_SUBMITTED


def reduction_amount(requested, approved) -> float:
	"""Director reduction. Never mutates the original requested amount."""
	return flt(requested) - flt(approved)


def funding_approval_is_recorded(workflow_state: str | None) -> bool:
	"""True only after the Director has approved. Draft/Pending are not approved."""
	return workflow_state in FUNDING_REQUEST_APPROVED_STATES


def funding_is_approved(workflow_state: str | None, docstatus: int | None = 0) -> bool:
	if workflow_state in INACTIVE_FUNDING_STATES:
		return False
	if not funding_approval_is_recorded(workflow_state):
		return False
	return cint_docstatus(docstatus) == 1


def funding_progress_state(
	current: str | None, total_funded: float, total_approved: float
) -> str | None:
	"""Payment-driven Funding Request state.

	Creating or submitting an Employee Advance is not payment, so paid can stay 0.
	Never reverse Funding in Progress back to Director Approved — that transition
	is not in the workflow and would block Employee Advance submit.
	"""
	if current not in (
		FUNDING_REQUEST_STATE_APPROVED,
		FUNDING_REQUEST_STATE_FUNDING,
		FUNDING_REQUEST_STATE_FUNDED,
	):
		return current
	funded = flt(total_funded)
	approved = flt(total_approved)
	if approved > 0 and funded + 0.005 >= approved:
		return FUNDING_REQUEST_STATE_FUNDED
	if funded > 0:
		return FUNDING_REQUEST_STATE_FUNDING
	if current == FUNDING_REQUEST_STATE_FUNDED:
		return FUNDING_REQUEST_STATE_FUNDING
	return current


PURCHASE_REQUEST_TYPES_REQUIRING_FUNDING = frozenset({"Purchase", "Subcontracting"})


def material_request_purchase_is_director_approved(material_request: str) -> bool:
	"""Purchase/Subcontracting may create a PO only after Director-approved funding."""
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
	if material_request_purchase_is_director_approved(material_request):
		return
	frappe.throw(
		_(
			"Material Request {0} must be on a Director-approved Funding Request "
			"before a Purchase Order or quotation can be created."
		).format(frappe.bold(material_request))
	)


def on_purchase_document_validate(doc, method=None) -> None:
	if cint_docstatus(doc.docstatus) == 2:
		return
	if not doc.is_new() and cint_docstatus(doc.docstatus) == 1:
		return
	seen = set()
	for row in doc.get("items") or []:
		mr_name = row.get("material_request")
		if not mr_name or mr_name in seen:
			continue
		seen.add(mr_name)
		assert_material_request_may_create_purchase_document(mr_name)


@frappe.whitelist()
def make_purchase_order(source_name, target_doc=None, args=None):
	assert_material_request_may_create_purchase_document(source_name)
	from erpnext.stock.doctype.material_request.material_request import (
		make_purchase_order as erpnext_make_purchase_order,
	)

	return erpnext_make_purchase_order(source_name, target_doc=target_doc, args=args)


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

	return erpnext_make_po_by_supplier(source_name, target_doc=target_doc, args=args)


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


def on_material_request_on_submit(doc, method=None) -> None:
	"""Align funding Workflow State after ERPNext submit (does not replace ERPNext status)."""
	if not doc.meta.has_field(MR_FUNDING_WORKFLOW_STATE_FIELD):
		return
	current = (doc.get(MR_FUNDING_WORKFLOW_STATE_FIELD) or "").strip()
	if current and current not in {MR_FUNDING_STATE_DRAFT, ""}:
		return
	next_state = (
		MR_FUNDING_STATE_UNFUNDED
		if doc.get("material_request_type") == MATERIAL_REQUEST_TYPE_OPERATIONAL
		else MR_FUNDING_STATE_SUBMITTED
	)
	doc.db_set(MR_FUNDING_WORKFLOW_STATE_FIELD, next_state, update_modified=False)


def _set_default_funding_workflow_state(doc) -> None:
	if not doc.meta.has_field(MR_FUNDING_WORKFLOW_STATE_FIELD):
		return
	if doc.get(MR_FUNDING_WORKFLOW_STATE_FIELD):
		return
	if cint_docstatus(doc.docstatus) >= 1:
		return
	doc.set(MR_FUNDING_WORKFLOW_STATE_FIELD, MR_FUNDING_STATE_DRAFT)


def _set_requester_defaults(doc) -> None:
	if not doc.get("custom_requested_by"):
		doc.custom_requested_by = frappe.session.user
	if doc.get("custom_employee"):
		return
	employee = frappe.db.get_value(
		"Employee",
		{"user_id": doc.custom_requested_by or frappe.session.user, "status": "Active"},
		"name",
	)
	if employee:
		doc.custom_employee = employee


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


def copy_project_from_employee_advance(doc, method=None) -> None:
	"""Payment Entry against an Employee Advance inherits the shipment Project."""
	if doc.get("project"):
		return
	for ref in doc.get("references") or []:
		if ref.reference_doctype != "Employee Advance" or not ref.reference_name:
			continue
		project = frappe.db.get_value(
			"Employee Advance", ref.reference_name, "custom_project"
		)
		if project:
			doc.project = project
			return


def on_payment_entry_on_submit(doc, method=None) -> None:
	sync_funding_requests_touched_by_payment_entry(doc)


def on_payment_entry_on_cancel(doc, method=None) -> None:
	sync_funding_requests_touched_by_payment_entry(doc)


# ── Employee Advance ─────────────────────────────────────────────────────────


def on_employee_advance_validate(doc, method=None) -> None:
	_populate_employee_advance_from_request(doc)
	_validate_employee_advance_funding_gate(doc)
	if doc.get("custom_funding_request"):
		doc.repay_unclaimed_amount_from_salary = 0


def on_employee_advance_on_submit(doc, method=None) -> None:
	sync_funding_request_paid_amounts(doc.get("custom_funding_request"))


def on_employee_advance_on_cancel(doc, method=None) -> None:
	sync_funding_request_paid_amounts(doc.get("custom_funding_request"))


def _populate_employee_advance_from_request(doc) -> None:
	mr_name = doc.get("custom_material_request")
	if not mr_name:
		return
	mr = frappe.db.get_value(
		"Material Request",
		mr_name,
		[
			"custom_employee",
			"custom_request_description",
			"custom_project",
			"custom_funding_request",
			"custom_approved_amount",
		],
		as_dict=True,
	)
	if not mr:
		return
	if not doc.get("custom_funding_request") and mr.custom_funding_request:
		doc.custom_funding_request = mr.custom_funding_request
	if not doc.get("custom_project") and mr.custom_project:
		doc.custom_project = mr.custom_project
	if not doc.get("employee") and mr.custom_employee:
		doc.employee = mr.custom_employee
	if not doc.get("purpose"):
		summary = get_material_request_item_summary(mr_name)
		description = mr.custom_request_description or ""
		doc.purpose = " — ".join(part for part in (summary, description) if part)
	if not flt(doc.advance_amount):
		approved = flt(mr.custom_approved_amount)
		if approved:
			doc.advance_amount = approved
			return
		row = _funding_request_row(doc.get("custom_funding_request") or "", mr_name)
		if row:
			doc.advance_amount = max(flt(row.approved_amount) - flt(row.funded_amount), 0)


def _validate_employee_advance_funding_gate(doc) -> None:
	fr_name = doc.get("custom_funding_request")
	if not fr_name:
		if doc.get("custom_material_request"):
			frappe.throw(
				_(
					"Employee Advance for a Material Request can only be created from an "
					"approved Funding Request."
				)
			)
		return

	fr = frappe.db.get_value(
		"Funding Request",
		fr_name,
		["workflow_state", "docstatus"],
		as_dict=True,
	)
	if not fr or not funding_is_approved(fr.workflow_state, fr.docstatus):
		frappe.throw(
			_("Cannot create an Employee Advance for an unapproved Funding Request {0}.").format(
				frappe.bold(fr_name)
			)
		)

	mr_name = doc.get("custom_material_request")
	if not mr_name:
		return
	row = _funding_request_row(fr_name, mr_name)
	if not row:
		frappe.throw(
			_("Material Request {0} is not on Funding Request {1}.").format(
				frappe.bold(mr_name), frappe.bold(fr_name)
			)
		)
	approved = flt(row.approved_amount)
	already_funded = flt(row.funded_amount)
	# When submitting, this document's amount is not yet in funded_amount.
	remaining = approved - already_funded
	if flt(doc.advance_amount) > remaining + 0.005:
		frappe.throw(
			_(
				"Employee Advance amount {0} exceeds the Director-approved remaining "
				"amount {1} for Material Request {2}."
			).format(
				frappe.bold(doc.advance_amount),
				frappe.bold(remaining),
				frappe.bold(mr_name),
			)
		)


def _funding_request_row(funding_request: str, material_request: str):
	rows = frappe.get_all(
		"Funding Request Material Request",
		filters={"parent": funding_request, "material_request": material_request},
		fields=["name", "approved_amount", "funded_amount", "requested_amount"],
		limit=1,
	)
	return rows[0] if rows else None


def _apply_employee_advance_to_funding_request(doc, sign: int) -> None:
	sync_funding_request_paid_amounts(doc.get("custom_funding_request"))


def sync_funding_requests_touched_by_payment_entry(doc) -> None:
	seen = set()
	for ref in doc.get("references") or []:
		fr_name = None
		if ref.reference_doctype == "Employee Advance" and ref.reference_name:
			fr_name = frappe.db.get_value(
				"Employee Advance", ref.reference_name, "custom_funding_request"
			)
		elif ref.reference_doctype == "Purchase Invoice" and ref.reference_name:
			fr_name = _funding_request_from_purchase_invoice(ref.reference_name)
		if fr_name and fr_name not in seen:
			seen.add(fr_name)
			sync_funding_request_paid_amounts(fr_name)


def sync_funding_request_paid_amounts(funding_request: str | None) -> None:
	"""Funded Amount is cash actually paid, not the Employee Advance / PO draft."""
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
		# "transition not allowed" (e.g. Funding in Progress → Director Approved).
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
		return _paid_against_employee_advances(funding_request, material_request)
	if mr_type in PURCHASE_REQUEST_TYPES_REQUIRING_FUNDING:
		return _paid_against_purchase_orders(material_request)
	return 0.0


def _paid_against_employee_advances(funding_request: str, material_request: str) -> float:
	advances = frappe.get_all(
		"Employee Advance",
		filters={
			"custom_funding_request": funding_request,
			"custom_material_request": material_request,
			"docstatus": 1,
		},
		pluck="name",
	)
	if not advances:
		return 0.0
	paid = frappe.db.sql(
		"""
		select coalesce(sum(per.allocated_amount), 0)
		from `tabPayment Entry Reference` per
		inner join `tabPayment Entry` pe on pe.name = per.parent
		where pe.docstatus = 1
			and per.reference_doctype = 'Employee Advance'
			and per.reference_name in %(advances)s
		""",
		{"advances": advances},
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
	description = mr.get("custom_request_description")
	item_summary = get_material_request_item_summary(mr)
	if not description:
		description = item_summary
	employee_name = None
	if mr.get("custom_employee"):
		employee_name = frappe.db.get_value("Employee", mr.custom_employee, "employee_name")
	return {
		"material_request": mr.name,
		"employee": mr.get("custom_employee"),
		"employee_name": employee_name,
		"item_summary": item_summary,
		"description": description,
		"project": mr.get("custom_project") or get_material_request_project(mr.name),
		"requested_amount": requested,
		"approved_amount": 0,
		"reduction_amount": 0,
		"funded_amount": 0,
		"status": MR_FUNDING_STATE_ON_REQUEST,
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

	filters[MR_FUNDING_WORKFLOW_STATE_FIELD] = [
		"in",
		[MR_FUNDING_STATE_UNFUNDED, MR_FUNDING_STATE_SUBMITTED],
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
	fr_filters: dict = {"workflow_state": ["not in", list(INACTIVE_FUNDING_STATES)]}
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
def make_employee_advance(funding_request: str, material_request: str | None = None):
	frappe.has_permission("Funding Request", "write", throw=True)
	fr = frappe.get_doc("Funding Request", funding_request)
	_assert_funding_request_approved(fr)
	row = _employee_advance_target_row(fr, material_request)
	return _build_employee_advance(fr, row).as_dict()


@frappe.whitelist()
def make_employee_advances(funding_request: str) -> list[str]:
	"""Create one draft Employee Advance per remaining operational-expense row."""
	frappe.has_permission("Employee Advance", "create", throw=True)
	fr = frappe.get_doc("Funding Request", funding_request)
	_assert_funding_request_approved(fr)
	created = []
	for row in _outstanding_rows(fr, MATERIAL_REQUEST_TYPE_OPERATIONAL):
		if _open_employee_advance_exists(fr.name, row.material_request):
			continue
		adv = _build_employee_advance(fr, row)
		if not adv.advance_account:
			adv.flags.ignore_validate = True
		adv.insert(ignore_permissions=True, ignore_mandatory=True)
		created.append(adv.name)
	if not created:
		frappe.throw(_("No Employee Advances left to create."))
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
		if po.meta.has_field("custom_funding_request"):
			po.custom_funding_request = fr.name
		po.insert(ignore_permissions=True, ignore_mandatory=True)
		created.append(po.name)
	if not created:
		frappe.throw(_("No Purchase Orders left to create."))
	return created


@frappe.whitelist()
def make_funding_payments(funding_request: str) -> list[str]:
	"""Create draft Payment Entries for submitted unpaid Employee Advances."""
	frappe.has_permission("Payment Entry", "create", throw=True)
	fr = frappe.get_doc("Funding Request", funding_request)
	_assert_funding_request_approved(fr)
	from hrms.overrides.employee_payment_entry import get_payment_entry_for_employee

	created = []
	for adv_name in _unpaid_employee_advances(fr.name):
		pe = get_payment_entry_for_employee("Employee Advance", adv_name)
		if isinstance(pe, dict):
			pe = frappe.get_doc(pe)
		pe.insert(ignore_permissions=True, ignore_mandatory=True)
		created.append(pe.name)
	if not created:
		frappe.throw(_("No payments to create."))
	return created


def _assert_funding_request_approved(fr) -> None:
	if not funding_is_approved(fr.workflow_state, fr.docstatus):
		frappe.throw(
			_("Cannot create payment documents before Director approval of {0}.").format(
				frappe.bold(fr.name)
			)
		)


def _employee_advance_target_row(fr, material_request: str | None):
	targets = [
		row
		for row in fr.material_requests
		if row.material_request and (not material_request or row.material_request == material_request)
	]
	if material_request and not targets:
		frappe.throw(
			_("Material Request {0} is not on Funding Request {1}.").format(
				frappe.bold(material_request), frappe.bold(fr.name)
			)
		)
	if not material_request:
		targets = [
			row for row in targets if flt(row.approved_amount) - flt(row.funded_amount) > 0
		]
	if not targets:
		frappe.throw(_("No remaining approved amount to advance."))
	return targets[0]


def _build_employee_advance(fr, row):
	remaining = flt(row.approved_amount) - flt(row.funded_amount)
	if remaining <= 0:
		frappe.throw(_("No remaining approved amount to advance."))
	if not row.employee:
		frappe.throw(
			_("Set Employee on Material Request {0} before creating an Employee Advance.").format(
				frappe.bold(row.material_request)
			)
		)
	adv = frappe.new_doc("Employee Advance")
	adv.employee = row.employee
	adv.posting_date = nowdate()
	adv.purpose = " — ".join(
		part for part in (get_material_request_item_summary(row.material_request), row.description) if part
	) or row.material_request
	adv.advance_amount = remaining
	adv.custom_material_request = row.material_request
	adv.custom_funding_request = fr.name
	adv.custom_project = row.project
	adv.company = fr.company
	adv.repay_unclaimed_amount_from_salary = 0
	adv.advance_account = _employee_advance_receivable_account(row.employee, fr.company)
	return adv


def _employee_advance_receivable_account(employee: str | None, company: str | None) -> str | None:
	"""HRMS requires account_type Receivable. Skip Holding / Payable defaults."""
	candidates = []
	if employee:
		candidates.append(frappe.db.get_value("Employee", employee, "employee_advance_account"))
	if company:
		candidates.append(
			frappe.db.get_value("Company", company, "default_employee_advance_account")
		)
	for account in candidates:
		if account and frappe.db.get_value("Account", account, "account_type") == "Receivable":
			return account
	return None


def _outstanding_rows(fr, request_type: str | None, purchase: bool = False):
	out = []
	for row in fr.material_requests:
		if not row.material_request:
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


def _open_employee_advance_exists(funding_request: str, material_request: str) -> bool:
	return bool(
		frappe.db.exists(
			"Employee Advance",
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


def _unpaid_employee_advances(funding_request: str) -> list[str]:
	rows = frappe.get_all(
		"Employee Advance",
		filters={"custom_funding_request": funding_request, "docstatus": 1},
		fields=["name", "advance_amount", "paid_amount"],
	)
	return [
		row.name for row in rows if flt(row.advance_amount) - flt(row.paid_amount) > 0.005
	]


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
			if not _open_employee_advance_exists(fr.name, row.material_request):
				operational.append(payload)
		elif mr_type in PURCHASE_REQUEST_TYPES_REQUIRING_FUNDING:
			if not _open_purchase_order_exists(row.material_request):
				purchase.append(payload)
	payments = []
	for adv_name in _unpaid_employee_advances(fr.name):
		adv = frappe.db.get_value(
			"Employee Advance",
			adv_name,
			["name", "employee", "advance_amount", "paid_amount"],
			as_dict=True,
		)
		if not adv:
			continue
		employee_name = frappe.db.get_value("Employee", adv.employee, "employee_name")
		payments.append(
			{
				"employee_advance": adv.name,
				"employee_name": employee_name or adv.employee,
				"remaining": flt(adv.advance_amount) - flt(adv.paid_amount),
			}
		)
	return {"operational": operational, "purchase": purchase, "payments": payments}


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
				"items": ["Employee Advance"],
			}
		)
	for group in transactions:
		if group.get("label") in (_("Purchase"), "Purchase"):
			items = group.setdefault("items", [])
			if "Payment Entry" not in items:
				items.append("Payment Entry")
	non_standard = data.setdefault("non_standard_fieldnames", {})
	non_standard["Material Request"] = "custom_project"
	non_standard["Employee Advance"] = "custom_project"
	return data


def get_material_request_dashboard_data(data):
	transactions = data.setdefault("transactions", [])
	transactions.append(
		{"label": _("Funding"), "items": ["Funding Request", "Employee Advance"]}
	)
	non_standard = data.setdefault("non_standard_fieldnames", {})
	non_standard["Employee Advance"] = "custom_material_request"
	internal = data.setdefault("internal_links", {})
	internal["Funding Request"] = "custom_funding_request"
	return data


def get_employee_advance_dashboard_data(data):
	transactions = data.setdefault("transactions", [])
	transactions.append(
		{"label": _("Requisition"), "items": ["Material Request", "Funding Request"]}
	)
	internal = data.setdefault("internal_links", {})
	internal["Material Request"] = "custom_material_request"
	internal["Funding Request"] = "custom_funding_request"
	return data


# ── Setup (idempotent) ───────────────────────────────────────────────────────


def ensure_funding_request_setup() -> None:
	"""Role, custom fields, workflow. Safe to re-run."""
	if not frappe.db.exists("DocType", "Material Request"):
		return
	_ensure_director_role()
	ensure_funding_custom_fields()
	_preserve_legacy_purpose_in_description()
	ensure_material_request_type_label()
	ensure_material_request_type_options()
	if frappe.db.exists("DocType", "Funding Request") and frappe.db.exists("DocType", "Workflow"):
		ensure_funding_request_workflow()
	ensure_material_request_workflow_state_visible()


def _ensure_director_role() -> None:
	if frappe.db.exists("Role", DIRECTOR_ROLE):
		return
	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": DIRECTOR_ROLE,
			"desk_access": 1,
		}
	).insert(ignore_permissions=True)


def _preserve_legacy_purpose_in_description() -> None:
	"""Keep historical Purpose text on Request Description. Do not delete data."""
	if not frappe.db.has_column("Material Request", "custom_purpose"):
		return
	if not frappe.db.has_column("Material Request", "custom_request_description"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabMaterial Request`
		SET custom_request_description = custom_purpose
		WHERE IFNULL(custom_request_description, '') = ''
		  AND IFNULL(custom_purpose, '') != ''
		"""
	)


def ensure_funding_custom_fields() -> None:
	_ensure_material_request_fields()
	_ensure_employee_advance_fields()
	_ensure_purchase_order_fields()


def _ensure_material_request_fields() -> None:
	fields = [
		{
			"fieldname": "custom_employee",
			"label": "Employee",
			"fieldtype": "Link",
			"options": "Employee",
			"insert_after": "custom_requested_by_name",
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_purpose",
			"label": "Purpose (legacy)",
			"fieldtype": "Link",
			"options": "Material Request Purpose",
			"insert_after": "custom_employee",
			"hidden": 1,
			"read_only": 1,
			"in_list_view": 0,
			"in_standard_filter": 0,
			"description": "Historical classification. New requests use Item on the Items table.",
		},
		{
			"fieldname": "custom_request_description",
			"label": "Request Description",
			"fieldtype": "Small Text",
			"insert_after": "custom_purpose",
		},
		{
			"fieldname": "custom_project",
			"label": "Project / Shipment",
			"fieldtype": "Link",
			"options": "Project",
			"insert_after": "custom_request_description",
			"in_standard_filter": 1,
			"in_list_view": 1,
		},
		{
			"fieldname": "custom_requested_amount",
			"label": "Requested Amount (legacy)",
			"fieldtype": "Currency",
			"insert_after": "custom_project",
			"read_only": 1,
			"hidden": 1,
			"in_list_view": 0,
			"description": "Historical header total. Requested amount is now sum(Items.amount).",
		},
		{
			"fieldname": "custom_approved_amount",
			"label": "Approved Amount",
			"fieldtype": "Currency",
			"insert_after": "custom_requested_amount",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "custom_funding_request",
			"label": "Funding Request",
			"fieldtype": "Link",
			"options": "Funding Request",
			"insert_after": "custom_approved_amount",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_funding_status",
			"label": "Funding Status (legacy)",
			"fieldtype": "Link",
			"options": "Workflow State",
			"insert_after": "custom_funding_request",
			"read_only": 1,
			"hidden": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"in_standard_filter": 0,
			"description": "Replaced by standard workflow_state on Material Request.",
		},
	]
	for values in fields:
		if values["fieldname"] in (
			"custom_funding_status",
			"custom_purpose",
			"custom_requested_amount",
		):
			_upsert_cf("Material Request", values)
		else:
			_ensure_cf("Material Request", values)


def _ensure_purchase_order_fields() -> None:
	if not frappe.db.exists("DocType", "Purchase Order"):
		return
	_ensure_cf(
		"Purchase Order",
		{
			"fieldname": "custom_funding_request",
			"label": "Funding Request",
			"fieldtype": "Link",
			"options": "Funding Request",
			"insert_after": "company",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
		},
	)
	if not frappe.db.has_column("Purchase Order", "custom_funding_request"):
		return
	if not frappe.db.has_column("Material Request", "custom_funding_request"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabPurchase Order` po
		INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
		INNER JOIN `tabMaterial Request` mr ON mr.name = poi.material_request
		SET po.custom_funding_request = mr.custom_funding_request
		WHERE IFNULL(po.custom_funding_request, '') = ''
		  AND IFNULL(mr.custom_funding_request, '') != ''
		"""
	)


def _ensure_employee_advance_fields() -> None:
	if not frappe.db.exists("DocType", "Employee Advance"):
		return
	for values in (
		{
			"fieldname": "custom_material_request",
			"label": "Material Request",
			"fieldtype": "Link",
			"options": "Material Request",
			"insert_after": "purpose",
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_funding_request",
			"label": "Funding Request",
			"fieldtype": "Link",
			"options": "Funding Request",
			"insert_after": "custom_material_request",
			"in_standard_filter": 1,
		},
		{
			"fieldname": "custom_project",
			"label": "Project / Shipment",
			"fieldtype": "Link",
			"options": "Project",
			"insert_after": "custom_funding_request",
			"in_standard_filter": 1,
		},
	):
		_ensure_cf("Employee Advance", values)


def ensure_material_request_type_label() -> None:
	"""Keep ERPNext fulfillment type, but stop calling it Purpose."""
	name = "Material Request-material_request_type-label"
	if frappe.db.exists("Property Setter", name):
		current = frappe.db.get_value("Property Setter", name, "value")
		if current == "Request Type":
			return
		frappe.db.set_value("Property Setter", name, "value", "Request Type", update_modified=False)
		return
	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": "Material Request",
			"field_name": "material_request_type",
			"property": "label",
			"property_type": "Data",
			"value": "Request Type",
			"module": MODULE,
			"name": name,
		}
	).insert(ignore_permissions=True)


def ensure_material_request_workflow_state_visible() -> None:
	"""Show standard workflow_state as Funding Status (Frappe creates it hidden)."""
	name = f"Material Request-{MR_FUNDING_WORKFLOW_STATE_FIELD}"
	if not frappe.db.exists("Custom Field", name):
		return
	doc = frappe.get_doc("Custom Field", name)
	changed = False
	if doc.hidden:
		doc.hidden = 0
		changed = True
	if doc.label != "Funding Status":
		doc.label = "Funding Status"
		changed = True
	if not doc.in_standard_filter:
		doc.in_standard_filter = 1
		changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _select_option_list(options: str | None) -> list[str]:
	return [line.strip() for line in (options or "").replace("\r\n", "\n").split("\n") if line.strip()]


def erpnext_material_request_type_options() -> str:
	"""ERPNext Material Request.material_request_type options (DocField, not Property Setter)."""
	return (
		frappe.db.get_value(
			"DocField",
			{"parent": "Material Request", "fieldname": "material_request_type"},
			"options",
		)
		or ""
	)


def with_operational_expense_request_type(options: str | None = None) -> str:
	"""Keep ERPNext Request Types and append Operational Expense if missing."""
	values = _select_option_list(
		erpnext_material_request_type_options() if options is None else options
	)
	if MATERIAL_REQUEST_TYPE_OPERATIONAL not in values:
		values.append(MATERIAL_REQUEST_TYPE_OPERATIONAL)
	return "\n".join(values)


def ensure_material_request_type_options() -> None:
	"""Property Setter: extend ERPNext's Select options with Operational Expense only."""
	desired = with_operational_expense_request_type()
	name = "Material Request-material_request_type-options"
	if frappe.db.exists("Property Setter", name):
		current = frappe.db.get_value("Property Setter", name, "value")
		if current == desired:
			return
		frappe.db.set_value("Property Setter", name, "value", desired, update_modified=False)
		return
	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": "Material Request",
			"field_name": "material_request_type",
			"property": "options",
			"property_type": "Text",
			"value": desired,
			"module": MODULE,
			"name": name,
		}
	).insert(ignore_permissions=True)


def ensure_funding_request_workflow() -> None:
	if not frappe.db.exists("DocType", "Workflow"):
		return
	_ensure_workflow_states()
	_ensure_workflow_actions()
	_sync_funding_request_workflow()
	_sync_material_request_funding_workflow()
	_backfill_material_request_funding_states()


def _ensure_workflow_states() -> None:
	styles = {
		FUNDING_REQUEST_STATE_DRAFT: "Primary",
		FUNDING_REQUEST_STATE_PENDING: "Warning",
		FUNDING_REQUEST_STATE_APPROVED: "Success",
		FUNDING_REQUEST_STATE_FUNDING: "Info",
		FUNDING_REQUEST_STATE_FUNDED: "Success",
		FUNDING_REQUEST_STATE_COMPLETED: "Success",
		FUNDING_REQUEST_STATE_REJECTED: "Danger",
		FUNDING_REQUEST_STATE_CANCELLED: "Inverse",
		MR_FUNDING_STATE_SUBMITTED: "Primary",
		MR_FUNDING_STATE_UNFUNDED: "Warning",
		MR_FUNDING_STATE_ON_REQUEST: "Info",
	}
	for state_name, style in styles.items():
		if frappe.db.exists("Workflow State", state_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Workflow State",
				"workflow_state_name": state_name,
				"style": style,
			}
		).insert(ignore_permissions=True)


def _ensure_workflow_actions() -> None:
	for action_name in (
		FUNDING_REQUEST_ACTION_SUBMIT,
		FUNDING_REQUEST_ACTION_APPROVE,
		FUNDING_REQUEST_ACTION_REJECT,
		FUNDING_REQUEST_ACTION_START_FUNDING,
		FUNDING_REQUEST_ACTION_MARK_FUNDED,
		FUNDING_REQUEST_ACTION_COMPLETE,
		FUNDING_REQUEST_ACTION_CANCEL,
		MR_FUNDING_ACTION_SUBMIT,
		MR_FUNDING_ACTION_SUBMIT_REQUEST,
		MR_FUNDING_ACTION_CANCEL,
	):
		if frappe.db.exists("Workflow Action Master", action_name):
			continue
		frappe.get_doc(
			{"doctype": "Workflow Action Master", "workflow_action_name": action_name}
		).insert(ignore_permissions=True)


def _sync_funding_request_workflow() -> None:
	if frappe.db.exists("Workflow", FUNDING_REQUEST_WORKFLOW_NAME):
		workflow = frappe.get_doc("Workflow", FUNDING_REQUEST_WORKFLOW_NAME)
	else:
		workflow = frappe.new_doc("Workflow")
		workflow.workflow_name = FUNDING_REQUEST_WORKFLOW_NAME

	workflow.document_type = "Funding Request"
	workflow.workflow_state_field = "workflow_state"
	workflow.is_active = 1
	workflow.send_email_alert = 0
	workflow.override_status = 0

	workflow.states = []
	for row in _funding_workflow_states():
		workflow.append("states", row)
	workflow.transitions = []
	for row in _funding_workflow_transitions():
		workflow.append("transitions", row)
	workflow.save(ignore_permissions=True)


def _finance_roles() -> tuple[str, ...]:
	return ("Finance User", "Finance Manager", "Accounts User", "Accounts Manager")


def _state(state, doc_status, allow_edit) -> dict:
	return {
		"state": state,
		"doc_status": str(doc_status),
		"allow_edit": allow_edit,
		"is_optional_state": 0,
	}


def _transition(state, action, next_state, allowed, condition=None) -> dict:
	row = {
		"state": state,
		"action": action,
		"next_state": next_state,
		"allowed": allowed,
		"allow_self_approval": 1,
	}
	if condition:
		row["condition"] = condition
	return row


def _funding_workflow_states() -> list[dict]:
	return [
		_state(FUNDING_REQUEST_STATE_DRAFT, 0, "Finance User"),
		_state(FUNDING_REQUEST_STATE_PENDING, 0, DIRECTOR_ROLE),
		_state(FUNDING_REQUEST_STATE_APPROVED, 1, "Finance User"),
		_state(FUNDING_REQUEST_STATE_FUNDING, 1, "Finance User"),
		_state(FUNDING_REQUEST_STATE_FUNDED, 1, "Finance User"),
		_state(FUNDING_REQUEST_STATE_COMPLETED, 1, "Finance User"),
		_state(FUNDING_REQUEST_STATE_REJECTED, 0, "Finance User"),
		_state(FUNDING_REQUEST_STATE_CANCELLED, 2, "System Manager"),
	]


def _funding_workflow_transitions() -> list[dict]:
	rows: list[dict] = []
	for role in _finance_roles():
		rows.append(
			_transition(
				FUNDING_REQUEST_STATE_DRAFT,
				FUNDING_REQUEST_ACTION_SUBMIT,
				FUNDING_REQUEST_STATE_PENDING,
				role,
			)
		)
		rows.append(
			_transition(
				FUNDING_REQUEST_STATE_REJECTED,
				FUNDING_REQUEST_ACTION_SUBMIT,
				FUNDING_REQUEST_STATE_PENDING,
				role,
			)
		)
		rows.append(
			_transition(
				FUNDING_REQUEST_STATE_FUNDED,
				FUNDING_REQUEST_ACTION_COMPLETE,
				FUNDING_REQUEST_STATE_COMPLETED,
				role,
			)
		)
		rows.append(
			_transition(
				FUNDING_REQUEST_STATE_APPROVED,
				FUNDING_REQUEST_ACTION_CANCEL,
				FUNDING_REQUEST_STATE_CANCELLED,
				role,
			)
		)
		rows.append(
			_transition(
				FUNDING_REQUEST_STATE_FUNDING,
				FUNDING_REQUEST_ACTION_CANCEL,
				FUNDING_REQUEST_STATE_CANCELLED,
				role,
			)
		)
	rows.append(
		_transition(
			FUNDING_REQUEST_STATE_PENDING,
			FUNDING_REQUEST_ACTION_APPROVE,
			FUNDING_REQUEST_STATE_APPROVED,
			DIRECTOR_ROLE,
		)
	)
	rows.append(
		_transition(
			FUNDING_REQUEST_STATE_PENDING,
			FUNDING_REQUEST_ACTION_REJECT,
			FUNDING_REQUEST_STATE_REJECTED,
			DIRECTOR_ROLE,
		)
	)
	return rows


def _sync_material_request_funding_workflow() -> None:
	if frappe.db.exists("Workflow", MR_FUNDING_WORKFLOW_NAME):
		workflow = frappe.get_doc("Workflow", MR_FUNDING_WORKFLOW_NAME)
	else:
		workflow = frappe.new_doc("Workflow")
		workflow.workflow_name = MR_FUNDING_WORKFLOW_NAME

	frappe.clear_cache(doctype="Material Request")
	workflow.document_type = "Material Request"
	workflow.workflow_state_field = MR_FUNDING_WORKFLOW_STATE_FIELD
	workflow.is_active = 1
	workflow.send_email_alert = 0
	# Don't Override Status: keep ERPNext Material Request.status (Draft/Submitted/Ordered/…).
	workflow.override_status = 1

	workflow.states = []
	for row in _mr_funding_workflow_states():
		workflow.append("states", row)
	workflow.transitions = []
	for row in _mr_funding_workflow_transitions():
		workflow.append("transitions", row)
	workflow.save(ignore_permissions=True)


def _backfill_material_request_funding_states() -> None:
	"""Copy legacy custom_funding_status onto workflow_state; fill missing states."""
	field = MR_FUNDING_WORKFLOW_STATE_FIELD
	if not frappe.db.has_column("Material Request", field):
		return
	if frappe.db.has_column("Material Request", "custom_funding_status"):
		frappe.db.sql(
			f"""
			UPDATE `tabMaterial Request`
			SET `{field}` = custom_funding_status
			WHERE IFNULL(`{field}`, '') = ''
			  AND IFNULL(custom_funding_status, '') != ''
			"""
		)
	frappe.db.sql(
		f"""
		UPDATE `tabMaterial Request`
		SET `{field}` = %(draft)s
		WHERE docstatus = 0
		  AND IFNULL(`{field}`, '') IN ('', %(unfunded)s)
		""",
		{"draft": MR_FUNDING_STATE_DRAFT, "unfunded": MR_FUNDING_STATE_UNFUNDED},
	)
	frappe.db.sql(
		f"""
		UPDATE `tabMaterial Request`
		SET `{field}` = %(submitted)s
		WHERE docstatus = 1
		  AND IFNULL(custom_funding_request, '') = ''
		  AND IFNULL(material_request_type, '') != %(oe)s
		  AND IFNULL(`{field}`, '') IN ('', %(unfunded)s)
		""",
		{
			"submitted": MR_FUNDING_STATE_SUBMITTED,
			"oe": MATERIAL_REQUEST_TYPE_OPERATIONAL,
			"unfunded": MR_FUNDING_STATE_UNFUNDED,
		},
	)
	frappe.db.sql(
		f"""
		UPDATE `tabMaterial Request`
		SET `{field}` = %(unfunded)s
		WHERE docstatus = 1
		  AND IFNULL(custom_funding_request, '') = ''
		  AND material_request_type = %(oe)s
		  AND IFNULL(`{field}`, '') = ''
		""",
		{"unfunded": MR_FUNDING_STATE_UNFUNDED, "oe": MATERIAL_REQUEST_TYPE_OPERATIONAL},
	)
	frappe.db.sql(
		f"""
		UPDATE `tabMaterial Request`
		SET `{field}` = %(cancelled)s
		WHERE docstatus = 2
		  AND IFNULL(`{field}`, '') IN ('', %(unfunded)s, %(draft)s)
		""",
		{
			"cancelled": MR_FUNDING_STATE_CANCELLED,
			"unfunded": MR_FUNDING_STATE_UNFUNDED,
			"draft": MR_FUNDING_STATE_DRAFT,
		},
	)
	if frappe.db.exists("DocType", "Funding Request Material Request"):
		frappe.db.sql(
			"""
			UPDATE `tabFunding Request Material Request`
			SET status = %(approved)s
			WHERE status = 'Reduced'
			""",
			{"approved": MR_FUNDING_STATE_APPROVED},
		)


def _requester_roles() -> tuple[str, ...]:
	return (
		"Stock User",
		"Purchase User",
		"Stock Manager",
		"Purchase Manager",
		"Employee",
		"System Manager",
	)


def _mr_funding_workflow_states() -> list[dict]:
	return [
		_state(MR_FUNDING_STATE_DRAFT, 0, "Stock User"),
		_state(MR_FUNDING_STATE_SUBMITTED, 1, "Stock User"),
		_state(MR_FUNDING_STATE_UNFUNDED, 1, "Finance User"),
		_state(MR_FUNDING_STATE_ON_REQUEST, 1, "Finance User"),
		_state(MR_FUNDING_STATE_PENDING, 1, DIRECTOR_ROLE),
		_state(MR_FUNDING_STATE_APPROVED, 1, "Finance User"),
		_state(MR_FUNDING_STATE_FUNDED, 1, "Finance User"),
		_state(MR_FUNDING_STATE_REJECTED, 1, "Finance User"),
		_state(MR_FUNDING_STATE_CANCELLED, 2, "System Manager"),
	]


def _mr_funding_workflow_transitions() -> list[dict]:
	rows: list[dict] = []
	for role in _requester_roles():
		rows.append(
			_transition(
				MR_FUNDING_STATE_DRAFT,
				MR_FUNDING_ACTION_SUBMIT,
				MR_FUNDING_STATE_SUBMITTED,
				role,
				condition=NON_OE_WORKFLOW_CONDITION,
			)
		)
		rows.append(
			_transition(
				MR_FUNDING_STATE_DRAFT,
				MR_FUNDING_ACTION_SUBMIT_REQUEST,
				MR_FUNDING_STATE_UNFUNDED,
				role,
				condition=OE_WORKFLOW_CONDITION,
			)
		)
		rows.append(
			_transition(
				MR_FUNDING_STATE_SUBMITTED,
				MR_FUNDING_ACTION_CANCEL,
				MR_FUNDING_STATE_CANCELLED,
				role,
				condition=NON_OE_WORKFLOW_CONDITION,
			)
		)
		rows.append(
			_transition(
				MR_FUNDING_STATE_UNFUNDED,
				MR_FUNDING_ACTION_CANCEL,
				MR_FUNDING_STATE_CANCELLED,
				role,
				condition=OE_WORKFLOW_CONDITION,
			)
		)
		rows.append(
			_transition(
				MR_FUNDING_STATE_REJECTED,
				MR_FUNDING_ACTION_CANCEL,
				MR_FUNDING_STATE_CANCELLED,
				role,
				condition=OE_WORKFLOW_CONDITION,
			)
		)
	for role in _finance_roles():
		rows.append(
			_transition(
				MR_FUNDING_STATE_DRAFT,
				MR_FUNDING_ACTION_SUBMIT_REQUEST,
				MR_FUNDING_STATE_UNFUNDED,
				role,
				condition=OE_WORKFLOW_CONDITION,
			)
		)
		rows.append(
			_transition(
				MR_FUNDING_STATE_UNFUNDED,
				MR_FUNDING_ACTION_CANCEL,
				MR_FUNDING_STATE_CANCELLED,
				role,
				condition=OE_WORKFLOW_CONDITION,
			)
		)
	return rows
