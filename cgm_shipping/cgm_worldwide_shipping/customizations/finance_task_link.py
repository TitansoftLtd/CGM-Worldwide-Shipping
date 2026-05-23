"""Link Purchase Invoice / Payment Entry to sea finance Tasks and Project."""
from __future__ import annotations

import frappe
from frappe.utils import flt, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
	is_sea_payment_task,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	payment_entry_allocates_purchase_invoice,
)


def ensure_finance_custom_fields() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_shipment_fields import (
		_create_cf,
	)

	for dt, insert_after in (
		("Purchase Invoice", "project"),
		("Payment Entry", "project"),
	):
		_create_cf(
			dt,
			{
				"fieldname": "custom_cgm_source_task",
				"label": "CGM Source Task",
				"fieldtype": "Link",
				"options": "Task",
				"insert_after": insert_after,
				"read_only": 1,
				"no_copy": 1,
			},
		)


def _task_finance_context(task) -> dict:
	if not is_sea_payment_task(task):
		frappe.throw(
			"This action is only for sea import finance payment tasks "
			"(UCR, permits, line charges, entry, KPA)."
		)
	if not task.project:
		frappe.throw("Task must be linked to a <b>Project</b> before creating finance documents.")

	company = task.company or frappe.db.get_value("Project", task.project, "company")
	return {
		"task": task.name,
		"project": task.project,
		"company": company,
		"subject": task.subject,
		"sequence_no": task.get("custom_sequence_no"),
		"purchase_invoice": task.get("custom_purchase_invoice"),
		"payment_entry": task.get("custom_payment_entry"),
	}


def get_default_purchase_item_code(company: str | None = None) -> str:
	"""Default PI item for permit / clearance lines."""
	settings_item = None
	if frappe.db.exists("DocType", "CGM Shipping Settings"):
		settings_item = frappe.db.get_single_value(
			"CGM Shipping Settings", "custom_default_purchase_item"
		)
	if settings_item and frappe.db.exists("Item", settings_item):
		return settings_item

	for name in ("CGM-CLEARANCE-CHARGE", "Import Clearance Charge"):
		if frappe.db.exists("Item", name):
			return name

	filters = {"is_purchase_item": 1, "disabled": 0}
	item = frappe.db.get_value("Item", filters, "name", order_by="modified desc")
	if item:
		return item

	frappe.throw(
		"Set <b>Default Purchase Item</b> on <b>CGM Shipping Settings</b> "
		"(or create Item <b>CGM-CLEARANCE-CHARGE</b>) for auto-filled permit lines on Purchase Invoice."
	)


def get_permit_rows_for_purchase_invoice(task) -> list[dict]:
	"""Permit rows with invoice + amount for PI line pre-fill (task 6 / 15 finance)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
		seed_finance_task_permits_from_project,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
		PERMIT_REGISTER_FIELD,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
		PERMIT_STAGE_BY_TASK_SEQ,
		TASK_PERMITS_FIELD,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if seq not in (6,):
		return []

	if task.meta.has_field(TASK_PERMITS_FIELD) and not task.get(TASK_PERMITS_FIELD):
		seed_finance_task_permits_from_project(task)
		task.reload()

	rows: list = list(task.get(TASK_PERMITS_FIELD) or [])

	if not rows and task.project:
		stage = PERMIT_STAGE_BY_TASK_SEQ.get(5 if seq == 6 else 15, "Pre-clearance")
		project = frappe.get_doc("Project", task.project)
		rows = [
			r
			for r in project.get(PERMIT_REGISTER_FIELD) or []
			if r.permit_type and r.get("payment_invoice") and (r.stage or stage) == stage
		]

	out = []
	for row in rows:
		if not row.permit_type:
			continue
		out.append(
			{
				"permit_type": row.permit_type,
				"invoice_amount": flt(row.get("invoice_amount")),
				"payment_invoice": row.get("payment_invoice"),
				"stage": row.get("stage"),
			}
		)
	return out


def build_permit_purchase_invoice_lines(task) -> list[dict]:
	"""Purchase Invoice Item rows from Task / Project permits."""
	permit_rows = get_permit_rows_for_purchase_invoice(task)
	if not permit_rows:
		return []

	item_code = get_default_purchase_item_code(task.company)
	lines = []
	for row in permit_rows:
		amount = flt(row.get("invoice_amount"))
		label = row.get("permit_type") or "Permit"
		desc = f"Pre-clearance permit — {label}"
		invoice_ref = row.get("payment_invoice")
		if invoice_ref:
			desc += f" (ref: {invoice_ref.split('/')[-1]})"
		lines.append(
			{
				"item_code": item_code,
				"item_name": desc,
				"description": desc,
				"qty": 1,
				"rate": amount,
				"amount": amount,
				"project": task.project,
			}
		)
	return lines


@frappe.whitelist()
def get_task_finance_defaults(task_name: str) -> dict:
	"""Defaults for Purchase Invoice / Payment Entry opened from a finance Task."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	ctx = _task_finance_context(task)
	if int(task.get("custom_sequence_no") or 0) == 6:
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			seed_finance_task_permits_from_project,
		)

		seed_finance_task_permits_from_project(task)
		task.reload()
	permit_rows = get_permit_rows_for_purchase_invoice(task)
	permit_lines = build_permit_purchase_invoice_lines(task)
	remarks = f"{task.subject} ({task.name}) — {ctx['project']}"
	if permit_rows:
		remarks += " | Permits: " + ", ".join(r["permit_type"] for r in permit_rows if r.get("permit_type"))

	return {
		**ctx,
		"permit_line_items": permit_lines,
		"purchase_invoice_defaults": {
			"project": ctx["project"],
			"company": ctx["company"],
			"custom_cgm_source_task": task.name,
			"remarks": remarks,
		},
	}


def apply_project_from_task_to_purchase_invoice(purchase_invoice: str, task_name: str) -> None:
	"""Set Project (and source task) on PI from the finance task."""
	if not purchase_invoice or not task_name:
		return
	task = frappe.get_doc("Task", task_name)
	if not task.project:
		return

	updates = {}
	pi_meta = frappe.get_meta("Purchase Invoice")
	if pi_meta.has_field("project"):
		updates["project"] = task.project
	if pi_meta.has_field("custom_cgm_source_task"):
		updates["custom_cgm_source_task"] = task.name

	if updates:
		frappe.db.set_value("Purchase Invoice", purchase_invoice, updates, update_modified=True)

	# Propagate project to line items when header was empty.
	pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
	changed = False
	for row in pi.get("items") or []:
		if not row.project:
			row.project = task.project
			changed = True
	if changed:
		pi.save(ignore_permissions=True)


def purchase_invoice_validate_from_task(doc, method=None):
	"""On save/submit: keep Project aligned with source finance task."""
	task_name = doc.get("custom_cgm_source_task")
	if not task_name and doc.get("remarks"):
		import re

		match = re.search(r"TASK-\d+", doc.remarks or "")
		if match:
			task_name = match.group(0)
	if not task_name or not frappe.db.exists("Task", task_name):
		return
	task = frappe.get_doc("Task", task_name)
	if not task.project:
		return
	if doc.meta.has_field("project") and not doc.project:
		doc.project = task.project
	if doc.meta.has_field("custom_cgm_source_task") and not doc.custom_cgm_source_task:
		doc.custom_cgm_source_task = task.name
	for row in doc.get("items") or []:
		if not row.project:
			row.project = task.project


def payment_entry_validate_from_task(doc, method=None):
	"""Ensure PE project matches PI / task when created from Make Payment on task."""
	task_name = doc.get("custom_cgm_source_task")
	if task_name and frappe.db.exists("Task", task_name):
		project = frappe.db.get_value("Task", task_name, "project")
		if project and doc.meta.has_field("project") and not doc.project:
			doc.project = project


def link_purchase_invoice_to_task_enhanced(task_name: str, purchase_invoice: str) -> dict:
	"""Link submitted PI to task and sync Project."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		notify_finance_for_task,
	)

	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	if not purchase_invoice or not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw("Purchase Invoice not found.")

	task = frappe.get_doc("Task", task_name)
	_task_finance_context(task)

	pi_status = frappe.db.get_value("Purchase Invoice", purchase_invoice, "docstatus")
	if int(pi_status or 0) != 1:
		frappe.throw("Purchase Invoice must be submitted before linking to the task.")

	apply_project_from_task_to_purchase_invoice(purchase_invoice, task_name)

	task_fields = frappe.get_meta("Task")
	if task_fields.has_field("custom_purchase_invoice"):
		task.custom_purchase_invoice = purchase_invoice
	task.save(ignore_permissions=True)
	notify_finance_for_task(task.name)

	return {"task": task.name, "purchase_invoice": purchase_invoice, "project": task.project}


def complete_task_with_payment_enhanced(task_name: str, payment_entry: str) -> dict:
	"""Link submitted PE to task; require allocation against task PI; complete task."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(f"Task {task_name} not found")
	if not payment_entry or not frappe.db.exists("Payment Entry", payment_entry):
		frappe.throw(f"Payment Entry {payment_entry} not found")

	payment_status = frappe.db.get_value("Payment Entry", payment_entry, "docstatus")
	if int(payment_status or 0) != 1:
		frappe.throw("Payment Entry must be submitted before linking it to the task.")

	task = frappe.get_doc("Task", task_name)
	_task_finance_context(task)
	task_fields = frappe.get_meta("Task")

	if is_sea_payment_task(task) and task_fields.has_field("custom_purchase_invoice"):
		pi_name = task.get("custom_purchase_invoice")
		if not pi_name:
			frappe.throw(
				"Create and submit a Purchase Invoice from this task first, then use <b>Make Payment</b>."
			)
		if not payment_entry_allocates_purchase_invoice(payment_entry, pi_name):
			frappe.throw(
				f"Payment Entry must allocate against Purchase Invoice <b>{pi_name}</b>. "
				"Use <b>Make Payment</b> on the task (do not create a blank Payment Entry)."
			)

	pe_meta = frappe.get_meta("Payment Entry")
	pe_updates = {}
	if pe_meta.has_field("project") and task.project:
		pe_updates["project"] = task.project
	if pe_meta.has_field("custom_cgm_source_task"):
		pe_updates["custom_cgm_source_task"] = task.name
	if pe_updates:
		frappe.db.set_value("Payment Entry", payment_entry, pe_updates, update_modified=True)

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
		apply_finance_payment_to_project_permits,
		sync_task_permits_to_project,
	)

	if task_fields.has_field("custom_payment_entry"):
		task.custom_payment_entry = payment_entry

	# Task 6 (permit payment): record PE only — complete after receipts verified.
	if int(task.get("custom_sequence_no") or 0) == 6:
		task.save(ignore_permissions=True)
		apply_finance_payment_to_project_permits(task)
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			notify_operations_upload_receipts,
			seed_finance_task_permits_from_project,
		)

		seed_finance_task_permits_from_project(task)
		sync_task_permits_to_project(task)
		notify_operations_upload_receipts(task)
		return {
			"task": task.name,
			"status": task.status,
			"payment_entry": payment_entry,
			"auto_completed": False,
			"message": (
				"Payment recorded. Operations must upload payment receipts; "
				"Finance must verify receipts before completing this task."
			),
		}

	task.completed_by = frappe.session.user
	task.completed_on = now_datetime()
	task.status = "Completed"
	task.save(ignore_permissions=True)
	apply_finance_payment_to_project_permits(task)

	return {
		"task": task.name,
		"status": task.status,
		"payment_entry": payment_entry,
		"auto_completed": True,
	}


@frappe.whitelist()
def sync_finance_docs_from_task(task_name: str) -> dict:
	"""Backfill Project on PI linked to a finance task (e.g. after upgrade)."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	task = frappe.get_doc("Task", task_name)
	out = {"task": task_name, "project": task.project}
	if task.get("custom_purchase_invoice"):
		apply_project_from_task_to_purchase_invoice(task.custom_purchase_invoice, task_name)
		out["purchase_invoice"] = task.custom_purchase_invoice
	return out
