"""Link Purchase Invoice / Payment Entry to sea finance Tasks and Project."""
from __future__ import annotations

import frappe
from frappe.utils import flt, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
	is_sea_payment_task,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.service import (
	is_permit_finance_payment_task,
	is_ucr_finance_payment_task,
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
	"""Permit rows with invoice + amount for PI line pre-fill (permit finance steps)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
		PERMIT_REGISTER_FIELD,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
		TASK_PERMITS_FIELD,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.service import (
		get_permit_stage_for_sequence,
		is_permit_finance_payment_task,
		permit_finance_by_application_sequence,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if not is_permit_finance_payment_task(seq):
		return []

	if task.meta.has_field(TASK_PERMITS_FIELD) and not task.get(TASK_PERMITS_FIELD):
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			ensure_finance_permit_rows_saved,
		)

		ensure_finance_permit_rows_saved(task)
		task.reload()

	rows: list = list(task.get(TASK_PERMITS_FIELD) or [])

	if not rows and task.project:
		app_seq = next(
			(app for app, fin in permit_finance_by_application_sequence().items() if fin == seq),
			None,
		)
		stage = get_permit_stage_for_sequence(app_seq) if app_seq else "Pre-clearance"
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.permit_item_mapping import (
		get_purchase_item_for_permit_type,
	)

	permit_rows = get_permit_rows_for_purchase_invoice(task)
	if not permit_rows:
		return []

	lines = []
	for row in permit_rows:
		permit_type = row.get("permit_type") or "Permit"
		amount = flt(row.get("invoice_amount"))
		if not amount:
			continue

		item_code = get_purchase_item_for_permit_type(permit_type, task.company)
		item_name = frappe.db.get_value("Item", item_code, "item_name") or permit_type
		desc = f"Pre-clearance permit - {permit_type}"
		invoice_ref = row.get("payment_invoice")
		if invoice_ref:
			desc += f" (ref: {invoice_ref.split('/')[-1]})"
		lines.append(
			{
				"item_code": item_code,
				"item_name": item_name,
				"description": desc,
				"qty": 1,
				"rate": amount,
				"amount": amount,
				"project": task.project,
				"permit_type": permit_type,
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
	if is_permit_finance_payment_task(int(task.get("custom_sequence_no") or 0)):
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			ensure_finance_permit_rows_saved,
		)

		ensure_finance_permit_rows_saved(task)
		task.reload()
	permit_rows = get_permit_rows_for_purchase_invoice(task)
	permit_lines = build_permit_purchase_invoice_lines(task)
	remarks = f"{task.subject} ({task.name}) - {ctx['project']}"
	if is_ucr_finance_payment_task(int(task.get("custom_sequence_no") or 0)):
		from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
			get_ucr_application_task,
		)

		app_task = get_ucr_application_task(task.project) if task.project else None
		if app_task:
			remarks += f" | UCR invoice on task {app_task}"
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

	# Avoid pi.save() here - it deadlocks when called from Purchase Invoice on_submit.
	frappe.db.sql(
		"""
		UPDATE `tabPurchase Invoice Item`
		SET project = %s
		WHERE parent = %s AND IFNULL(project, '') = ''
		""",
		(task.project, purchase_invoice),
	)


def _set_task_fields(task_name: str, values: dict) -> None:
	"""Update task finance link fields without triggering full save hooks."""
	meta = frappe.get_meta("Task")
	updates = {k: v for k, v in values.items() if meta.has_field(k)}
	if updates:
		frappe.db.set_value("Task", task_name, updates, update_modified=True)


def _enqueue_finance_job(method: str, **kwargs) -> None:
	"""Run linking in a separate job after commit (avoids Task row lock conflicts)."""

	def _enqueue():
		frappe.enqueue(
			f"cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.{method}",
			queue="short",
			enqueue_after_commit=True,
			**kwargs,
		)

	frappe.db.after_commit.add(_enqueue)


def _find_payment_entry_for_purchase_invoice(purchase_invoice: str) -> str | None:
	rows = frappe.db.sql(
		"""
		SELECT pe.name
		FROM `tabPayment Entry` pe
		INNER JOIN `tabPayment Entry Reference` ref ON ref.parent = pe.name
		WHERE ref.reference_doctype = 'Purchase Invoice'
		  AND ref.reference_name = %s
		  AND pe.docstatus = 1
		ORDER BY pe.modified DESC
		LIMIT 1
		""",
		purchase_invoice,
		pluck=True,
	)
	return rows[0] if rows else None


def _resolve_purchase_invoice_for_task(task, payment_entry: str) -> str | None:
	task_name = task.name
	pi_name = task.get("custom_purchase_invoice")
	if pi_name and frappe.db.exists("Purchase Invoice", pi_name):
		return pi_name

	ref_pi = frappe.db.get_value(
		"Payment Entry Reference",
		{"parent": payment_entry, "reference_doctype": "Purchase Invoice"},
		"reference_name",
	)
	if ref_pi:
		_set_task_fields(task_name, {"custom_purchase_invoice": ref_pi})
		return ref_pi

	return frappe.db.get_value(
		"Purchase Invoice",
		{"custom_cgm_source_task": task_name, "docstatus": 1},
		"name",
		order_by="modified desc",
	)


def job_link_pi_to_task(task_name: str, purchase_invoice: str) -> None:
	"""Background: link PI to task; if already paid, link PE too."""
	try:
		link_purchase_invoice_to_task_enhanced(task_name, purchase_invoice, notify=False)
		pe_name = _find_payment_entry_for_purchase_invoice(purchase_invoice)
		if pe_name:
			job_link_pe_to_task(task_name, pe_name)
	except Exception:
		frappe.log_error(
			title="CGM link PI to task failed",
			message=f"PI {purchase_invoice} → task {task_name}",
		)


def job_link_pe_to_task(task_name: str, payment_entry: str) -> None:
	"""Background: ensure PI + PE are linked on the finance task."""
	try:
		task = frappe.get_doc("Task", task_name)
		pi_name = _resolve_purchase_invoice_for_task(task, payment_entry)
		if pi_name and task.get("custom_purchase_invoice") != pi_name:
			link_purchase_invoice_to_task_enhanced(task_name, pi_name, notify=False)
		complete_task_with_payment_enhanced(task_name, payment_entry)
	except Exception:
		frappe.log_error(
			title="CGM link PE to task failed",
			message=f"PE {payment_entry} → task {task_name}",
		)


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


def purchase_invoice_on_submit(doc, method=None) -> None:
	"""Link submitted PI to the finance task after commit (avoid submit deadlocks)."""
	task_name = doc.get("custom_cgm_source_task")
	if not task_name or not frappe.db.exists("Task", task_name):
		return
	task = frappe.get_doc("Task", task_name)
	if not is_sea_payment_task(task):
		return
	if task.get("custom_purchase_invoice") == doc.name:
		return
	_enqueue_finance_job("job_link_pi_to_task", task_name=task_name, purchase_invoice=doc.name)


def payment_entry_on_submit(doc, method=None) -> None:
	"""Link submitted PE to the finance task in a background job."""
	task_name = doc.get("custom_cgm_source_task")
	if not task_name:
		task_name = _task_from_payment_references(doc)
	if not task_name or not frappe.db.exists("Task", task_name):
		return
	task = frappe.get_doc("Task", task_name)
	if not is_sea_payment_task(task):
		return
	if task.get("custom_payment_entry") == doc.name:
		return
	_enqueue_finance_job("job_link_pe_to_task", task_name=task_name, payment_entry=doc.name)


def _task_from_payment_references(doc) -> str | None:
	for row in doc.get("references") or []:
		if row.reference_doctype != "Purchase Invoice" or not row.reference_name:
			continue
		task_name = frappe.db.get_value(
			"Purchase Invoice", row.reference_name, "custom_cgm_source_task"
		)
		if task_name:
			return task_name
	return None


def payment_entry_validate_from_task(doc, method=None):
	"""Ensure PE project / source task match the finance task or its Purchase Invoice."""
	if not doc.get("custom_cgm_source_task"):
		for row in doc.get("references") or []:
			if row.reference_doctype == "Purchase Invoice" and row.reference_name:
				task_name = frappe.db.get_value(
					"Purchase Invoice", row.reference_name, "custom_cgm_source_task"
				)
				if task_name and doc.meta.has_field("custom_cgm_source_task"):
					doc.custom_cgm_source_task = task_name
					break

	task_name = doc.get("custom_cgm_source_task")
	if task_name and frappe.db.exists("Task", task_name):
		project = frappe.db.get_value("Task", task_name, "project")
		if project and doc.meta.has_field("project") and not doc.project:
			doc.project = project


def link_purchase_invoice_to_task_enhanced(
	task_name: str, purchase_invoice: str, *, notify: bool = True
) -> dict:
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
	project = task.project

	if task.get("custom_purchase_invoice") == purchase_invoice:
		return {"task": task.name, "purchase_invoice": purchase_invoice, "project": project}

	pi_status = frappe.db.get_value("Purchase Invoice", purchase_invoice, "docstatus")
	if int(pi_status or 0) != 1:
		frappe.throw("Purchase Invoice must be submitted before linking to the task.")

	apply_project_from_task_to_purchase_invoice(purchase_invoice, task_name)
	_set_task_fields(task_name, {"custom_purchase_invoice": purchase_invoice})
	if notify:
		notify_finance_for_task(task_name)

	return {"task": task_name, "purchase_invoice": purchase_invoice, "project": project}


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

	if task.get("custom_payment_entry") == payment_entry:
		return {
			"task": task.name,
			"status": task.status,
			"payment_entry": payment_entry,
			"auto_completed": task.status == "Completed",
			"message": "Payment already linked to this task.",
		}

	if is_sea_payment_task(task) and task_fields.has_field("custom_purchase_invoice"):
		pi_name = _resolve_purchase_invoice_for_task(task, payment_entry)
		if not pi_name:
			frappe.throw(
				"Create and submit a Purchase Invoice from this task first, then pay from that invoice."
			)
		if task.get("custom_purchase_invoice") != pi_name:
			_set_task_fields(task.name, {"custom_purchase_invoice": pi_name})
		if not payment_entry_allocates_purchase_invoice(payment_entry, pi_name):
			frappe.throw(
				f"Payment Entry must allocate against Purchase Invoice <b>{pi_name}</b>. "
				"Use <b>Payment</b> on the Purchase Invoice (Create menu)."
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

	seq = int(task.get("custom_sequence_no") or 0)

	# UCR / permit finance: record PE only - complete after receipts verified.
	if is_ucr_finance_payment_task(seq) or is_permit_finance_payment_task(seq):
		if task_fields.has_field("custom_payment_entry"):
			_set_task_fields(task.name, {"custom_payment_entry": payment_entry})
		task = frappe.get_doc("Task", task.name)

		frappe.flags.cgm_skip_task_project_sync = True
		try:
			if is_permit_finance_payment_task(seq):
				apply_finance_payment_to_project_permits(task)
				from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
					notify_declarant_upload_permit_receipts,
					seed_finance_task_permits_from_project,
				)

				seed_finance_task_permits_from_project(task)
				sync_task_permits_to_project(task)
				notify_declarant_upload_permit_receipts(task)
				message = (
					"Payment recorded. Declarant must upload payment receipts and permit "
					"certificates on Apply for Pre-Clearance Permits; Finance must verify "
					"receipts before completing this task."
				)
			else:
				from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
					notify_operations_upload_ucr_receipt,
					sync_ucr_payment_to_idf_record,
				)

				sync_ucr_payment_to_idf_record(task)
				notify_operations_upload_ucr_receipt(task)
				message = (
					"Payment recorded. Declarant must upload the UCR payment receipt on "
					"<b>Create UCR (IDF)</b>; Finance verifies the receipt before completing this task."
				)
		finally:
			frappe.flags.cgm_skip_task_project_sync = False

		return {
			"task": task.name,
			"status": task.status,
			"payment_entry": payment_entry,
			"auto_completed": False,
			"message": message,
		}

	task.completed_by = frappe.session.user
	task.completed_on = now_datetime()
	task.status = "Completed"
	frappe.flags.cgm_skip_task_project_sync = True
	try:
		task.save(ignore_permissions=True)
	finally:
		frappe.flags.cgm_skip_task_project_sync = False
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
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	out = {"task": task_name, "project": task.project}
	if task.get("custom_purchase_invoice"):
		apply_project_from_task_to_purchase_invoice(task.custom_purchase_invoice, task_name)
		out["purchase_invoice"] = task.custom_purchase_invoice
	return out


@frappe.whitelist()
def sync_finance_links_from_documents(task_name: str) -> dict:
	"""Link submitted PI/PE that reference this task (repair / backfill)."""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	pi_name = frappe.db.get_value(
		"Purchase Invoice",
		{"custom_cgm_source_task": task_name, "docstatus": 1},
		"name",
		order_by="modified desc",
	)
	if not pi_name:
		frappe.throw("No submitted Purchase Invoice found for this task.")
	job_link_pi_to_task(task_name, pi_name)
	task = frappe.get_doc("Task", task_name)
	return {
		"task": task_name,
		"purchase_invoice": task.get("custom_purchase_invoice") or pi_name,
		"payment_entry": task.get("custom_payment_entry"),
		"message": "Finance documents linked to this task.",
	}
