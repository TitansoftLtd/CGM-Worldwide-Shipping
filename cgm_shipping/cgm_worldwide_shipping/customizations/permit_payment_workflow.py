"""Permit invoice → Finance → Payment → Declarant receipt → Finance verify → Complete."""
from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications.constants import (
	PERMIT_INVOICES_TO_FINANCE,
	PERMIT_RECEIPTS_FOR_DECLARANT,
	PERMIT_RECEIPTS_VERIFY_FINANCE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications.service import (
	send_notification,
	workflow_notify_message,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.permissions.service import (
	user_has_finance_department_access,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
	TASK_PERMITS_FIELD,
	sync_task_permits_to_project,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements.service import (
	PRE_CLEARANCE_STAGE,
	get_permit_finance_sequence_for_application,
	get_permit_stage_for_sequence,
	get_pre_clearance_permit_application_sequence,
	is_permit_application_task,
	is_permit_finance_payment_task,
	permit_application_sequences,
	permit_finance_by_application_sequence,
)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

FINANCE_AUDIENCE = "Finance"
DECLARANT_AUDIENCE = "Declarant"


# ------------------------------------------------------------------
# Task lookups
# ------------------------------------------------------------------


def task_sequence(task) -> int:
	return int(task.get("custom_sequence_no") or 0)


def get_task_name_by_sequence(project: str, sequence_no: int) -> str | None:
	if not project or not sequence_no:
		return None
	return frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": sequence_no,
		},
		"name",
	)


def get_permit_application_task_name(project: str, sequence_no: int) -> str | None:
	return get_task_name_by_sequence(project, sequence_no)


def get_finance_permit_task_name(
	project: str,
	application_sequence_no: int | None = None,
) -> str | None:
	if application_sequence_no is None:
		application_sequence_no = get_pre_clearance_permit_application_sequence()
	if not application_sequence_no:
		return None
	finance_seq = get_permit_finance_sequence_for_application(application_sequence_no)
	if not finance_seq:
		return None
	return get_task_name_by_sequence(project, finance_seq)


def get_pre_clearance_permit_application_task_name(project: str) -> str | None:
	seq = get_pre_clearance_permit_application_sequence()
	return get_task_name_by_sequence(project, seq) if seq else None


def is_pre_clearance_permit_application_task(task) -> bool:
	seq = task_sequence(task)
	return is_permit_application_task(seq) and get_permit_stage_for_sequence(seq) == PRE_CLEARANCE_STAGE


def is_pre_clearance_finance_permit_task(task) -> bool:
	return is_permit_finance_payment_task(task_sequence(task))


def is_permit_application_task_doc(task) -> bool:
	return is_permit_application_task(task_sequence(task))


# ------------------------------------------------------------------
# Permit invoice state
# ------------------------------------------------------------------


def has_all_permit_invoices(task) -> bool:
	rows = task.get(TASK_PERMITS_FIELD) or []
	return bool(rows) and all(r.permit_type and r.get("payment_invoice") for r in rows)


def permit_invoices_submitted(task_name: str) -> bool:
	if not task_name or not frappe.db.exists("Task", task_name):
		return False
	if frappe.db.get_value("Task", task_name, "custom_permit_invoices_submitted"):
		return True
	if not frappe.has_permission("Task", doc=task_name, ptype="read", throw=False):
		project = frappe.db.get_value("Task", task_name, "project")
		seq = int(frappe.db.get_value("Task", task_name, "custom_sequence_no") or 0)
		if project and is_permit_application_task(seq):
			stage = get_permit_stage_for_sequence(seq)
			return project_has_submitted_permit_invoices(project, stage)
		return False
	task = frappe.get_doc("Task", task_name)
	return has_all_permit_invoices(task)


def project_has_submitted_permit_invoices(
	project: str, stage: str = PRE_CLEARANCE_STAGE
) -> bool:
	for seq in permit_application_sequences():
		task_name = get_task_name_by_sequence(project, seq)
		if not task_name:
			continue
		if get_permit_stage_for_sequence(seq) != stage:
			continue
		if permit_invoices_submitted(task_name):
			return True
	return False


def finance_payment_completed(project: str, application_seq: int | None = None) -> bool:
	if application_seq is None:
		application_seq = get_pre_clearance_permit_application_sequence()
	if not application_seq:
		return False
	fin_name = get_finance_permit_task_name(project, application_seq)
	if not fin_name:
		return False
	pe = frappe.db.get_value("Task", fin_name, "custom_payment_entry")
	if not pe or not frappe.db.exists("Payment Entry", pe):
		return False
	return int(frappe.db.get_value("Payment Entry", pe, "docstatus") or 0) == 1


# ------------------------------------------------------------------
# Row helpers
# ------------------------------------------------------------------


def build_permit_row_payload(row) -> dict:
	return {
		"permit_type": row.get("permit_type"),
		"stage": row.get("stage") or PRE_CLEARANCE_STAGE,
		"payment_invoice": row.get("payment_invoice"),
		"invoice_amount": row.get("invoice_amount"),
		"payment_receipt": row.get("payment_receipt"),
		"permit_document": row.get("permit_document"),
		"receipt_verified": row.get("receipt_verified"),
		"status": row.get("status") or "Invoice Submitted",
		"clearance_phase": row.get("clearance_phase") or "Not Started",
	}


def get_application_permit_rows(application_task_name: str) -> list[dict]:
	return frappe.get_all(
		"Permit Register",
		filters={
			"parent": application_task_name,
			"parenttype": "Task",
			"parentfield": TASK_PERMITS_FIELD,
		},
		fields=[
			"permit_type",
			"stage",
			"payment_invoice",
			"invoice_amount",
			"payment_receipt",
			"permit_document",
			"receipt_verified",
			"status",
			"clearance_phase",
		],
		order_by="idx asc",
	)


# ------------------------------------------------------------------
# Synchronization
# ------------------------------------------------------------------


def seed_finance_permit_rows_from_project(finance_task, *, save: bool = True) -> bool:
	"""Fallback: copy pre-clearance permit rows from Project register."""
	if finance_task.get(TASK_PERMITS_FIELD):
		return False

	from cgm_shipping.cgm_worldwide_shipping.customizations.project import PERMIT_REGISTER_FIELD

	project = frappe.get_doc("Project", finance_task.project)
	added = False
	for row in project.get(PERMIT_REGISTER_FIELD) or []:
		if row.stage != PRE_CLEARANCE_STAGE or not row.permit_type or not row.get("payment_invoice"):
			continue
		finance_task.append(
			TASK_PERMITS_FIELD,
			{
				"permit_type": row.permit_type,
				"stage": row.stage,
				"payment_invoice": row.get("payment_invoice"),
				"invoice_amount": row.get("invoice_amount"),
				"purchase_invoice": row.get("purchase_invoice"),
				"payment_entry": row.get("payment_entry"),
				"payment_receipt": row.get("payment_receipt"),
				"receipt_verified": row.get("receipt_verified"),
				"status": row.get("status") or "Invoice Submitted",
			},
		)
		added = True

	if added and save:
		frappe.flags.cgm_syncing_permit_finance_rows = True
		try:
			finance_task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_permit_finance_rows = False
	return added


def sync_permit_invoices_to_finance_task(finance_task, *, save: bool = True) -> bool:
	"""Copy submitted permit invoices from application task → finance permit task."""
	if frappe.flags.get("cgm_permit_finance_completing"):
		return False
	if not is_pre_clearance_finance_permit_task(finance_task):
		return False
	if not finance_task.meta.has_field(TASK_PERMITS_FIELD) or not finance_task.project:
		return False

	app_name = get_permit_application_task_name(
		finance_task.project, get_pre_clearance_permit_application_sequence()
	)
	if not app_name:
		return False

	app_rows = get_application_permit_rows(app_name)
	app_rows = [r for r in app_rows if r.get("permit_type") and r.get("payment_invoice")]
	if not app_rows:
		return seed_finance_permit_rows_from_project(finance_task, save=save)

	existing = {
		r.permit_type: r for r in finance_task.get(TASK_PERMITS_FIELD) or [] if r.permit_type
	}
	changed = False
	for row in app_rows:
		data = build_permit_row_payload(row)
		fin_row = existing.get(row.permit_type)
		if fin_row:
			for key, value in data.items():
				if value and fin_row.get(key) != value:
					fin_row.set(key, value)
					changed = True
		else:
			finance_task.append(TASK_PERMITS_FIELD, data)
			changed = True

	if changed and save:
		frappe.flags.cgm_syncing_permit_finance_rows = True
		try:
			finance_task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_permit_finance_rows = False
	return changed


def ensure_finance_permit_rows_saved(finance_task) -> bool:
	if not is_pre_clearance_finance_permit_task(finance_task):
		return False
	return sync_permit_invoices_to_finance_task(finance_task, save=True)


@frappe.whitelist()
def ensure_finance_permit_rows(task_name: str) -> dict:
	"""Load permit invoice rows onto Finance pays Pre-Clearance Permits (from declarant task)."""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if int(task.get("custom_sequence_no") or 0) != 6:
		frappe.throw("This action is only for <b>Finance pays Pre-Clearance Permits</b>.")
	added = ensure_finance_permit_rows_saved(task)
	task.reload()
	return {
		"added": added,
		"rows": len(task.get(TASK_PERMITS_FIELD) or []),
		"task": task.name,
	}
def seed_finance_task_permits_from_project(task) -> None:
	if not is_pre_clearance_finance_permit_task(task):
		return
	if not task.meta.has_field(TASK_PERMITS_FIELD) or not task.project:
		return
	sync_permit_invoices_to_finance_task(task, save=False)
	if not task.get(TASK_PERMITS_FIELD):
		seed_finance_permit_rows_from_project(task, save=False)


def merge_project_permits_into_application_task(task, *, save: bool = False) -> bool:
	seq = task_sequence(task)
	if not is_permit_application_task(seq) or not task.project:
		return False
	if not task.meta.has_field(TASK_PERMITS_FIELD):
		return False

	from cgm_shipping.cgm_worldwide_shipping.customizations.project import PERMIT_REGISTER_FIELD

	if not frappe.db.exists("Project", task.project):
		return False
	project = frappe.get_doc("Project", task.project)
	if not project.meta.has_field(PERMIT_REGISTER_FIELD):
		return False

	by_type = {
		r.permit_type: r for r in project.get(PERMIT_REGISTER_FIELD) or [] if r.permit_type
	}
	changed = False
	for row in task.get(TASK_PERMITS_FIELD) or []:
		if not row.permit_type:
			continue
		prow = by_type.get(row.permit_type)
		if not prow:
			continue
		for field in (
			"payment_receipt",
			"permit_document",
			"receipt_verified",
			"purchase_invoice",
			"payment_entry",
			"status",
			"clearance_phase",
		):
			val = prow.get(field)
			if val and row.get(field) != val:
				row.set(field, val)
				changed = True
	if changed and save:
		frappe.flags.cgm_syncing_permits = True
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_syncing_permits = False
	return changed


def prepare_finance_permit_task(application_task) -> str | None:
	seq = task_sequence(application_task)
	finance_name = get_finance_permit_task_name(application_task.project, seq)
	if not finance_name:
		return None
	finance_task = frappe.get_doc("Task", finance_name)
	sync_permit_invoices_to_finance_task(finance_task, save=True)
	return finance_name


# ------------------------------------------------------------------
# Notifications
# ------------------------------------------------------------------


@frappe.whitelist()
def submit_permit_invoices_to_finance(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_permit_application_task_doc(task):
		frappe.throw("This action is only for permit application tasks (5 and 15).")

	if not has_all_permit_invoices(task):
		frappe.throw(
			"Attach <b>Permit Invoice (for Finance)</b> on every row in <b>Task Permits</b> first."
		)

	sync_task_permits_to_project(task)
	task.custom_permit_invoices_submitted = 1
	task.save(ignore_permissions=True)

	finance_name = prepare_finance_permit_task(task)
	if not finance_name:
		frappe.throw(
			"Could not find <b>Finance pays Pre-Clearance Permits</b> on this project. "
			"Generate the sea task plan on the Project first."
		)
	finance_task = frappe.get_doc("Task", finance_name)

	notify_result = send_notification(
		PERMIT_INVOICES_TO_FINANCE,
		finance_task,
		audience=FINANCE_AUDIENCE,
	)

	from frappe.utils import get_url

	return {
		"task": task.name,
		"status": task.status,
		"finance_task": finance_name,
		"finance_task_url": get_url(f"/app/task/{finance_name}"),
		**notify_result,
		"message": workflow_notify_message(
			"Finance notified on Finance pays Pre-Clearance Permits.",
			notify_result,
			audience=FINANCE_AUDIENCE,
		),
	}


def notify_declarant_upload_permit_receipts(task) -> dict:
	if not is_pre_clearance_finance_permit_task(task):
		return {"notified": 0}
	if not task.get("custom_payment_entry") or not task.project:
		return {"notified": 0}

	app_name = get_pre_clearance_permit_application_task_name(task.project)
	if not app_name:
		return {"notified": 0}
	app_task = frappe.get_doc("Task", app_name)

	result = send_notification(
		PERMIT_RECEIPTS_FOR_DECLARANT,
		app_task,
		audience=DECLARANT_AUDIENCE,
	)
	return {
		**result,
		"message": workflow_notify_message(
			"Declarant notified to upload permit receipts and certificates.",
			result,
			audience=DECLARANT_AUDIENCE,
		),
	}


def notify_finance_verify_receipts_for_task(task) -> dict:
	seq = task_sequence(task)
	if is_pre_clearance_permit_application_task(task) and task.project:
		fin_name = get_finance_permit_task_name(task.project, task_sequence(task))
		if fin_name:
			sync_permit_invoices_to_finance_task(frappe.get_doc("Task", fin_name), save=True)
			task = frappe.get_doc("Task", fin_name)
			seq = task_sequence(task)
	if not is_permit_finance_payment_task(seq):
		return {"notified": 0}

	rows = task.get(TASK_PERMITS_FIELD) or []
	if not any(r.get("payment_receipt") for r in rows):
		return {"notified": 0}

	result = send_notification(
		PERMIT_RECEIPTS_VERIFY_FINANCE,
		task,
		audience=FINANCE_AUDIENCE,
	)
	return {
		**result,
		"message": workflow_notify_message(
			"Finance notified to verify permit payment receipts.",
			result,
			audience=FINANCE_AUDIENCE,
		),
	}


@frappe.whitelist()
def notify_finance_verify_receipts(task_name: str) -> dict:
	if not task_name or not frappe.db.exists("Task", task_name):
		return {"notified": 0}
	task = frappe.get_doc("Task", task_name)
	return notify_finance_verify_receipts_for_task(task)


@frappe.whitelist()
def ensure_finance_permit_rows(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_pre_clearance_finance_permit_task(task):
		frappe.throw("This action is only for <b>Finance pays Pre-Clearance Permits</b>.")
	added = ensure_finance_permit_rows_saved(task)
	task.reload()
	return {
		"added": added,
		"rows": len(task.get(TASK_PERMITS_FIELD) or []),
		"task": task.name,
	}


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------


def validate_finance_permit_payment_task(task) -> None:
	if not is_pre_clearance_finance_permit_task(task):
		return

	app_name = get_pre_clearance_permit_application_task_name(task.project)
	if app_name and not permit_invoices_submitted(app_name):
		frappe.throw(
			"Permit invoices must be submitted to Finance from the "
			"<b>Apply for Pre-Clearance Permits</b> task first."
		)

	rows = task.get(TASK_PERMITS_FIELD) or []
	if not rows:
		frappe.throw(
			"Open this task after permit invoices are on the Project, or refresh the page "
			"to load <b>Task Permits</b>."
		)


def validate_permit_application_can_complete(task) -> None:
	if frappe.flags.get("cgm_auto_completing_sea_task"):
		return
	seq = task_sequence(task)
	if not is_permit_application_task(seq):
		return

	if not task.get("custom_permit_invoices_submitted"):
		frappe.throw(
			"Click <b>Notify Finance - invoices ready</b> before completing this task."
		)

	if not finance_payment_completed(task.project, seq):
		frappe.throw(
			"Finance must record payment on <b>Finance pays Pre-Clearance Permits</b> "
			"before this task can be completed."
		)

	merge_project_permits_into_application_task(task)
	rows = task.get(TASK_PERMITS_FIELD) or []
	if not rows:
		frappe.throw("Add permit rows on <b>Task Permits</b> first.")

	missing_receipts = [r.permit_type for r in rows if r.permit_type and not r.get("payment_receipt")]
	if missing_receipts:
		frappe.throw(
			"Upload <b>Payment Receipt</b> for each permit. Missing: "
			f"<b>{', '.join(missing_receipts)}</b>."
		)

	missing_certs = [r.permit_type for r in rows if r.permit_type and not r.get("permit_document")]
	if missing_certs:
		frappe.throw(
			"Upload <b>Permit Certificate</b> for each permit. Missing: "
			f"<b>{', '.join(missing_certs)}</b>."
		)

	unverified = [r.permit_type for r in rows if r.permit_type and not r.get("receipt_verified")]
	if unverified:
		frappe.throw(
			"Finance must tick <b>Receipt Verified</b> on each permit (on "
			"<b>Finance pays Pre-Clearance Permits</b>) before completing. Pending: "
			f"<b>{', '.join(unverified)}</b>."
		)


def enforce_receipt_verified_permission(task) -> None:
	if is_permit_application_task_doc(task):
		if user_has_finance_department_access():
			return
		for row in task.get(TASK_PERMITS_FIELD) or []:
			if row.get("receipt_verified"):
				frappe.throw(
					"Only <b>Finance</b> can mark <b>Receipt Verified</b>. "
					"Use <b>Finance pays Pre-Clearance Permits</b>."
				)
		return
	if not is_pre_clearance_finance_permit_task(task):
		return
	if user_has_finance_department_access():
		return
	for row in task.get(TASK_PERMITS_FIELD) or []:
		if row.get("receipt_verified"):
			frappe.throw("Only <b>Finance</b> can mark <b>Receipt Verified</b> on permit rows.")


# ------------------------------------------------------------------
# Completion
# ------------------------------------------------------------------


def can_complete_finance_permit_task(task) -> bool:
	if not is_pre_clearance_finance_permit_task(task):
		return False
	if task.status in ("Completed", "Cancelled"):
		return False
	if not task.get("custom_purchase_invoice") or not task.get("custom_payment_entry"):
		return False
	if int(frappe.db.get_value("Payment Entry", task.custom_payment_entry, "docstatus") or 0) != 1:
		return False
	rows = [r for r in task.get(TASK_PERMITS_FIELD) or [] if r.permit_type]
	if not rows:
		return False
	return all(r.get("payment_receipt") and r.get("receipt_verified") for r in rows)


def mark_permit_task_completed(task) -> None:
	frappe.db.set_value(
		"Task",
		task.name,
		{
			"status": "Completed",
			"completed_by": task.completed_by or frappe.session.user,
			"completed_on": task.completed_on or now_datetime(),
			"progress": 100,
		},
		update_modified=True,
	)
	frappe.clear_document_cache("Task", task.name)


def run_finance_permit_completion_hooks(task) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
		sync_project_shipment_status_from_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
		apply_finance_payment_to_project_permits,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		refresh_project_shipment_documents,
	)

	frappe.flags.cgm_skip_task_project_sync = True
	try:
		sync_task_permits_to_project(task)
		apply_finance_payment_to_project_permits(task)
	finally:
		frappe.flags.cgm_skip_task_project_sync = False

	mark_permit_task_completed(task)
	task.reload()
	close_permit_application_when_finance_done(task)
	if task.project:
		refresh_project_shipment_documents(task.project)
		sync_project_shipment_status_from_tasks(task.project)
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{"task": task.name, "status": "Completed", "project": task.project},
	)
	frappe.publish_realtime("cgm_project_tracking_refresh", {"project": task.project})


def mark_all_permit_receipts_verified(task_name: str) -> None:
	for row in frappe.get_all(
		"Permit Register",
		filters={
			"parent": task_name,
			"parenttype": "Task",
			"parentfield": TASK_PERMITS_FIELD,
		},
		fields=["name", "payment_receipt"],
	):
		if row.payment_receipt:
			frappe.db.set_value(
				"Permit Register", row.name, "receipt_verified", 1, update_modified=False
			)


def complete_finance_permit_workflow(task) -> bool:
	"""Verify receipts, sync project, complete finance + application tasks."""
	if frappe.flags.get("cgm_permit_finance_completing"):
		return False
	if not can_complete_finance_permit_task(task):
		return False

	frappe.flags.cgm_permit_finance_completing = True
	frappe.flags.cgm_auto_completing_sea_task = True
	try:
		task.completed_by = task.completed_by or frappe.session.user
		task.completed_on = task.completed_on or now_datetime()
		run_finance_permit_completion_hooks(task)
	finally:
		frappe.flags.cgm_auto_completing_sea_task = False
		frappe.flags.cgm_permit_finance_completing = False
	return True


def auto_complete_finance_permit_task(task) -> bool:
	return complete_finance_permit_workflow(task)


def close_permit_application_when_finance_done(task) -> None:
	if not is_pre_clearance_finance_permit_task(task) or task.status != "Completed":
		return
	app_name = get_pre_clearance_permit_application_task_name(task.project)
	if not app_name:
		return
	if frappe.db.get_value("Task", app_name, "status") == "Completed":
		return
	app = frappe.get_doc("Task", app_name)
	merge_project_permits_into_application_task(app)
	frappe.db.set_value(
		"Task",
		app_name,
		{
			"status": "Completed",
			"completed_by": task.completed_by or frappe.session.user,
			"completed_on": task.completed_on or now_datetime(),
			"progress": 100,
			"description": (
				"Permit invoices submitted to Finance; payment and receipt verification "
				f"completed on {task.name}."
			),
		},
		update_modified=True,
	)
	frappe.clear_document_cache("Task", app_name)


@frappe.whitelist()
def verify_all_permit_receipts(task_name: str) -> dict:
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_pre_clearance_finance_permit_task(task):
		frappe.throw("This action is only for <b>Finance pays Pre-Clearance Permits</b>.")

	if task.status == "Completed":
		app_name = (
			get_pre_clearance_permit_application_task_name(task.project)
			if task.project
			else None
		)
		return {
			"task": task.name,
			"status": task.status,
			"application_task": app_name,
			"application_status": frappe.db.get_value("Task", app_name, "status")
			if app_name
			else None,
			"auto_completed": True,
			"message": "Permit payment tasks are already completed.",
		}

	if not task.get("custom_payment_entry"):
		frappe.throw("Record payment on this task before verifying receipts.")

	rows = [r for r in task.get(TASK_PERMITS_FIELD) or [] if r.permit_type]
	if not rows:
		frappe.throw("No permit rows on this task. Refresh the page.")

	missing_receipts = [r.permit_type for r in rows if not r.get("payment_receipt")]
	if missing_receipts:
		frappe.throw(
			"Declarant must upload <b>Payment Receipt</b> on "
			"<b>Apply for Pre-Clearance Permits</b> first. Missing: "
			f"<b>{', '.join(missing_receipts)}</b>."
		)

	mark_all_permit_receipts_verified(task.name)
	task.reload()
	completed = complete_finance_permit_workflow(task)
	app_name = (
		get_pre_clearance_permit_application_task_name(task.project)
		if task.project
		else None
	)
	app_status = frappe.db.get_value("Task", app_name, "status") if app_name else None

	return {
		"task": task.name,
		"status": frappe.db.get_value("Task", task.name, "status"),
		"application_task": app_name,
		"application_status": app_status,
		"auto_completed": completed,
		"message": (
			"All permit receipts verified - finance and declarant tasks are completed."
			if completed
			else "Receipts verified. Tick any remaining rows or refresh the page."
		),
	}


@frappe.whitelist()
def ensure_permit_finance_task_completed(task_name: str) -> dict:
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	completed = auto_complete_finance_permit_task(task)
	app_name = (
		get_pre_clearance_permit_application_task_name(task.project)
		if task.project
		else None
	)
	return {
		"task": task.name,
		"status": frappe.db.get_value("Task", task.name, "status"),
		"application_task": app_name,
		"application_status": frappe.db.get_value("Task", app_name, "status") if app_name else None,
		"auto_completed": completed,
	}


@frappe.whitelist()
def get_permit_finance_workflow_status(task_name: str) -> dict:
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	rows = [r for r in task.get(TASK_PERMITS_FIELD) or [] if r.permit_type]
	pending_verify = [
		r.permit_type for r in rows if r.get("payment_receipt") and not r.get("receipt_verified")
	]
	missing_receipts = [r.permit_type for r in rows if not r.get("payment_receipt")]
	return {
		"task_status": task.status,
		"has_payment": bool(task.get("custom_payment_entry")),
		"pending_verify": pending_verify,
		"missing_receipts": missing_receipts,
		"ready_to_complete": can_complete_finance_permit_task(task),
	}


# ------------------------------------------------------------------
# Backward-compatible aliases (existing imports / patches)
# ------------------------------------------------------------------

PERMIT_FINANCE_SEQ_BY_APPLICATION = permit_finance_by_application_sequence()
all_permit_rows_have_invoices = has_all_permit_invoices
permit_invoices_ready = permit_invoices_submitted
permit_invoices_ready_for_project = project_has_submitted_permit_invoices
finance_permit_payment_recorded = finance_payment_completed
permit_finance_ready_to_complete = can_complete_finance_permit_task
try_auto_complete_permit_finance_task = auto_complete_finance_permit_task
get_permit_application_task = get_permit_application_task_name
get_permit_finance_task = get_finance_permit_task_name
