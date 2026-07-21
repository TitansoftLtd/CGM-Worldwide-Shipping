"""Workflow gates, UCR and permit payment flows."""
from __future__ import annotations



import frappe

SEA_IMPORT_WORKFLOW_NAME = "CGM Sea Import Workflow"


@frappe.request_cache
def get_workflow_task_gates() -> dict[str, dict]:
	"""Map shipment workflow status → gate row from CGM Shipping Settings."""
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("custom_sea_workflow_task_gates"):
		return {}

	rows = frappe.get_single("CGM Shipping Settings").get("custom_sea_workflow_task_gates") or []
	return {
		(row.shipment_workflow_state or "").strip(): {
			"min_completed_task_seq": int(row.min_completed_task_seq or 0),
			"gate_rule": row.gate_rule or "Standard",
		}
		for row in rows
		if (row.shipment_workflow_state or "").strip()
	}


def get_gate_for_state(workflow_state: str) -> dict | None:
	return get_workflow_task_gates().get((workflow_state or "").strip())


@frappe.request_cache
def get_sea_import_workflow_states() -> list[str]:
	"""Ordered Project workflow states from CGM Sea Import Workflow metadata."""
	if frappe.db.exists("Workflow", SEA_IMPORT_WORKFLOW_NAME):
		rows = frappe.get_all(
			"Workflow Document State",
			filters={"parent": SEA_IMPORT_WORKFLOW_NAME, "parenttype": "Workflow"},
			fields=["state"],
			order_by="idx asc",
		)
		states = [row.state for row in rows if row.state]
		if states:
			return states

	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
		DEFAULT_SEA_IMPORT_WORKFLOW_STATES,
	)

	return list(DEFAULT_SEA_IMPORT_WORKFLOW_STATES)


# ============================================================

"""Permit invoice → Finance → Payment → Declarant receipt → Finance verify → Complete."""
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
	PERMIT_INVOICES_TO_FINANCE,
	PERMIT_RECEIPTS_FOR_DECLARANT,
	PERMIT_RECEIPTS_VERIFY_FINANCE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
	send_notification,
	workflow_notify_message,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
	user_has_finance_department_access,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
	TASK_PERMITS_FIELD,
	sync_task_permits_to_project,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	PRE_CLEARANCE_STAGE,
	POST_CLEARANCE_STAGE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
	get_application_sequence_for_finance_task,
	get_permit_finance_sequence_for_application,
	get_permit_stage_for_sequence,
	get_post_clearance_permit_application_sequence,
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
	"""Resolve a sea-import task by sequence; accept CGM Task Template name or legacy key."""
	if not project or not sequence_no:
		return None
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		sea_import_flow_keys,
	)

	for flow_key in sea_import_flow_keys():
		name = frappe.db.get_value(
			"Task",
			{
				"project": project,
				"custom_task_flow_key": flow_key,
				"custom_sequence_no": sequence_no,
			},
			"name",
		)
		if name:
			return name
	return None


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
	return is_permit_finance_task_doc(task)


def is_permit_finance_task_doc(task) -> bool:
	return is_permit_finance_payment_task(task_sequence(task))


def get_permit_application_task_for_finance(finance_task) -> str | None:
	if not finance_task.project:
		return None
	app_seq = get_application_sequence_for_finance_task(finance_task)
	if not app_seq:
		return None
	return get_task_name_by_sequence(finance_task.project, app_seq)


def permit_stage_for_finance_task(finance_task) -> str:
	app_seq = get_application_sequence_for_finance_task(finance_task)
	if app_seq:
		return get_permit_stage_for_sequence(app_seq)
	return PRE_CLEARANCE_STAGE


def finance_permit_task_label(finance_task) -> str:
	subject = (finance_task.get("subject") or "").strip()
	if subject:
		return subject
	stage = permit_stage_for_finance_task(finance_task)
	return f"Finance pays {stage} Permits"


def is_permit_application_task_doc(task) -> bool:
	return is_permit_application_task(task_sequence(task))


# ------------------------------------------------------------------
# Permit invoice state
# ------------------------------------------------------------------


def has_all_permit_invoices(task) -> bool:
	"""True when every permit row has the attachment required for its origin.

	Local rows need a payment invoice; Foreign rows need a permit certificate.
	"""
	from cgm_shipping.cgm_worldwide_shipping.doctype.permit_register.permit_register import (
		permit_row_ready_for_application,
	)

	rows = task.get(TASK_PERMITS_FIELD) or []
	return bool(rows) and all(permit_row_ready_for_application(r) for r in rows)


def payable_permit_rows(task) -> list:
	"""Permit rows that require the Finance payment path (Local origin)."""
	from cgm_shipping.cgm_worldwide_shipping.doctype.permit_register.permit_register import (
		permit_requires_payment,
	)

	return [
		r
		for r in task.get(TASK_PERMITS_FIELD) or []
		if r.get("permit_type") and permit_requires_payment(r)
	]


def has_all_payable_permit_invoices(task) -> bool:
	payable = payable_permit_rows(task)
	return bool(payable) and all(r.get("payment_invoice") for r in payable)


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


def task_has_recorded_payment(task) -> bool:
	"""Finance recorded payment via Journal Entry or a submitted Payment Entry."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		PERMIT_JOURNAL_ENTRY_FIELD,
		TASK_PERMITS_FIELD,
	)

	if is_permit_finance_task_doc(task):
		rows = permit_finance_rows(task)
		if not rows:
			# All-foreign (or empty) finance task has nothing to pay.
			return True
		for row in rows:
			je = row.get(PERMIT_JOURNAL_ENTRY_FIELD)
			if je and frappe.db.exists("Journal Entry", je):
				continue
			pe = row.get("payment_entry")
			if pe and frappe.db.exists("Payment Entry", pe):
				if int(frappe.db.get_value("Payment Entry", pe, "docstatus") or 0) == 1:
					continue
			return False
		return True

	if task.get("custom_journal_entry"):
		if frappe.db.exists("Journal Entry", task.custom_journal_entry):
			return True
	pe = task.get("custom_payment_entry")
	if pe and frappe.db.exists("Payment Entry", pe):
		return int(frappe.db.get_value("Payment Entry", pe, "docstatus") or 0) == 1
	return False


def permit_finance_rows(task) -> list:
	"""Payable permit rows on a finance task (Foreign origin is excluded)."""
	return payable_permit_rows(task)


def task_uses_permit_payment_pattern(task) -> bool:
	return is_permit_finance_task_doc(task) and bool(permit_finance_rows(task))


def validate_permit_finance_task_completion(task) -> None:
	"""Each permit row needs its own journal entry and verified receipt before completion."""
	if not is_permit_finance_task_doc(task):
		return
	rows = permit_finance_rows(task)
	if not rows:
		return
	missing_je = [r.permit_type for r in rows if not r.get("journal_entry")]
	if missing_je:
		frappe.throw(
			"Record a <b>Journal Entry</b> for each permit before completing. Missing: "
			f"<b>{', '.join(missing_je)}</b>."
		)
	unverified = [
		r.permit_type for r in rows if not r.get("receipt_verified") or not r.get("payment_receipt")
	]
	if unverified:
		frappe.throw(
			"Each permit needs a <b>Payment Receipt</b> and <b>Receipt Verified</b> before completing. "
			f"Pending: <b>{', '.join(unverified)}</b>."
		)


def finance_payment_completed(project: str, application_seq: int | None = None) -> bool:
	if application_seq is None:
		application_seq = get_pre_clearance_permit_application_sequence()
	if not application_seq:
		return False
	fin_name = get_finance_permit_task_name(project, application_seq)
	if not fin_name:
		return False
	return task_has_recorded_payment(frappe.get_doc("Task", fin_name))


# ------------------------------------------------------------------
# Row helpers
# ------------------------------------------------------------------


def build_permit_row_payload(row) -> dict:
	return {
		"permit_type": row.get("permit_type"),
		"origin": row.get("origin") or "Local",
		"stage": row.get("stage") or PRE_CLEARANCE_STAGE,
		"payment_invoice": row.get("payment_invoice"),
		"invoice_amount": row.get("invoice_amount"),
		"journal_entry": row.get("journal_entry"),
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
			"origin",
			"stage",
			"payment_invoice",
			"invoice_amount",
			"journal_entry",
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

	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import PERMIT_REGISTER_FIELD

	project = frappe.get_doc("Project", finance_task.project)
	stage = permit_stage_for_finance_task(finance_task)
	added = False
	for row in project.get(PERMIT_REGISTER_FIELD) or []:
		if row.stage != stage or not row.permit_type or not row.get("payment_invoice"):
			continue
		finance_task.append(
			TASK_PERMITS_FIELD,
			{
				"permit_type": row.permit_type,
				"origin": row.get("origin") or "Local",
				"stage": row.stage,
				"payment_invoice": row.get("payment_invoice"),
				"invoice_amount": row.get("invoice_amount"),
				"purchase_invoice": row.get("purchase_invoice"),
				"payment_entry": row.get("payment_entry"),
				"journal_entry": row.get("journal_entry"),
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
	if not is_permit_finance_task_doc(finance_task):
		return False
	if not finance_task.meta.has_field(TASK_PERMITS_FIELD) or not finance_task.project:
		return False

	app_seq = get_application_sequence_for_finance_task(finance_task)
	if not app_seq:
		return False
	app_name = get_permit_application_task_name(finance_task.project, app_seq)
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
	if not is_permit_finance_task_doc(finance_task):
		return False
	return sync_permit_invoices_to_finance_task(finance_task, save=True)


def seed_finance_task_permits_from_project(task) -> None:
	if not is_permit_finance_task_doc(task):
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

	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import PERMIT_REGISTER_FIELD

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
			"origin",
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


def _permit_invoices_pending_finance_notification(task) -> bool:
	"""True when Local permit invoices are ready but Finance has not been notified yet."""
	if not is_permit_application_task_doc(task):
		return False
	if task.get("custom_permit_invoices_submitted"):
		return False
	if not payable_permit_rows(task):
		return False
	return has_all_payable_permit_invoices(task)


def _mark_foreign_only_permits_ready(task) -> bool:
	"""When every row is Foreign and certificates are attached, skip Finance notify."""
	if not is_permit_application_task_doc(task):
		return False
	if payable_permit_rows(task):
		return False
	if not has_all_permit_invoices(task):
		return False
	if task.get("custom_permit_invoices_submitted"):
		return False
	if task.meta.has_field("custom_permit_invoices_submitted"):
		frappe.db.set_value(
			"Task",
			task.name,
			"custom_permit_invoices_submitted",
			1,
			update_modified=False,
		)
		task.custom_permit_invoices_submitted = 1
	sync_task_permits_to_project(task)
	return True


def _notify_finance_for_permit_invoices(task, *, strict: bool = True) -> dict | None:
	"""Sync permit invoices to Project/Finance task and send the finance notification."""
	sync_task_permits_to_project(task)

	finance_name = prepare_finance_permit_task(task)
	if not finance_name:
		stage = get_permit_stage_for_sequence(task_sequence(task))
		msg = (
			f"Could not find the <b>Finance pays {stage} Permits</b> task on this project. "
			"Generate the sea task plan on the Project first."
		)
		if strict:
			frappe.throw(msg)
		frappe.msgprint(msg, indicator="orange", alert=True)
		return None
	finance_task = frappe.get_doc("Task", finance_name)

	notify_result = send_notification(
		PERMIT_INVOICES_TO_FINANCE,
		finance_task,
		audience=FINANCE_AUDIENCE,
	)

	return {
		"task": task.name,
		"status": task.status,
		"finance_task": finance_name,
		"finance_task_url": get_url(f"/app/task/{finance_name}"),
		**notify_result,
		"message": workflow_notify_message(
			f"Finance notified on {finance_task.subject or 'permit finance task'}.",
			notify_result,
			audience=FINANCE_AUDIENCE,
		),
	}


def auto_submit_permit_invoices_to_finance_if_needed(task) -> dict | None:
	"""On save: notify Finance when Local permit invoices are attached (no manual submit)."""
	if frappe.flags.get("cgm_auto_submitting_permit_invoices"):
		return None
	if _mark_foreign_only_permits_ready(task):
		return None
	if (
		task.get("custom_permit_invoices_submitted")
		and not has_all_payable_permit_invoices(task)
		and payable_permit_rows(task)
		and not finance_payment_completed(task.get("project"), task_sequence(task))
	):
		if task.meta.has_field("custom_permit_invoices_submitted"):
			frappe.db.set_value(
				"Task", task.name, "custom_permit_invoices_submitted", 0, update_modified=False
			)
			task.custom_permit_invoices_submitted = 0
		return None
	if not _permit_invoices_pending_finance_notification(task):
		return None

	frappe.flags.cgm_auto_submitting_permit_invoices = True
	try:
		result = _notify_finance_for_permit_invoices(task, strict=False)
		if not result:
			return None
		if task.meta.has_field("custom_permit_invoices_submitted"):
			frappe.db.set_value(
				"Task",
				task.name,
				"custom_permit_invoices_submitted",
				1,
				update_modified=False,
			)
			task.custom_permit_invoices_submitted = 1
		return result
	finally:
		frappe.flags.cgm_auto_submitting_permit_invoices = False


@frappe.whitelist()
def submit_permit_invoices_to_finance(task_name: str) -> dict:
	"""Manual fallback; normal path is auto-submit when all permit invoices are attached."""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_permit_application_task_doc(task):
		frappe.throw("This action is only for permit application tasks (5 and 15).")

	if not payable_permit_rows(task):
		if has_all_permit_invoices(task):
			_mark_foreign_only_permits_ready(task)
			return {
				"task": task.name,
				"status": task.status,
				"message": (
					"All permits are <b>Foreign</b> — no Finance payment needed. "
					"Complete the task after certificates are attached."
				),
			}
		frappe.throw(
			"Attach <b>Permit Certificate</b> on every Foreign permit row before continuing."
		)

	if not has_all_payable_permit_invoices(task):
		frappe.throw(
			"Attach <b>Permit Invoice (for Finance)</b> on every <b>Local</b> row in "
			"<b>Task Permits</b> first. Foreign rows only need a certificate."
		)

	result = auto_submit_permit_invoices_to_finance_if_needed(task)
	if result:
		return result

	if task.meta.has_field("custom_permit_invoices_submitted"):
		task.custom_permit_invoices_submitted = 1
		task.save(ignore_permissions=True)
	return _notify_finance_for_permit_invoices(task)


def notify_declarant_upload_permit_receipts(task) -> dict:
	if not is_permit_finance_task_doc(task):
		return {"notified": 0}
	if not task_has_recorded_payment(task) or not task.project:
		return {"notified": 0}

	app_name = get_permit_application_task_for_finance(task)
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
	if not is_permit_finance_task_doc(task):
		frappe.throw("This action is only for permit finance payment tasks.")
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
	if not is_permit_finance_task_doc(task):
		return

	app_name = get_permit_application_task_for_finance(task)
	if app_name and not permit_invoices_submitted(app_name):
		stage = permit_stage_for_finance_task(task)
		frappe.throw(
			f"Permit invoices must be submitted to Finance from the "
			f"<b>{stage}</b> permit application task first."
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

	payable = payable_permit_rows(task)
	if payable:
		if not task.get("custom_permit_invoices_submitted"):
			frappe.throw(
				"Attach all <b>Local</b> permit invoices and save — Finance is notified "
				"automatically — before completing this task."
			)

		if not finance_payment_completed(task.project, seq):
			fin_seq = get_permit_finance_sequence_for_application(seq)
			fin_name = get_task_name_by_sequence(task.project, fin_seq) if fin_seq else None
			fin_label = (
				frappe.db.get_value("Task", fin_name, "subject")
				if fin_name
				else "Finance permit payment"
			)
			frappe.throw(
				f"Finance must record payment on <b>{fin_label}</b> before this task can be completed."
			)
	elif not has_all_permit_invoices(task):
		frappe.throw(
			"Attach <b>Permit Certificate</b> on every <b>Foreign</b> permit row before completing."
		)
	elif not task.get("custom_permit_invoices_submitted"):
		_mark_foreign_only_permits_ready(task)

	merge_project_permits_into_application_task(task)
	rows = task.get(TASK_PERMITS_FIELD) or []
	if not rows:
		frappe.throw("Add permit rows on <b>Task Permits</b> first.")

	missing_receipts = [
		r.permit_type for r in payable if r.permit_type and not r.get("payment_receipt")
	]
	if missing_receipts:
		frappe.throw(
			"Upload <b>Payment Receipt</b> for each Local permit. Missing: "
			f"<b>{', '.join(missing_receipts)}</b>."
		)

	missing_certs = [r.permit_type for r in rows if r.permit_type and not r.get("permit_document")]
	if missing_certs:
		frappe.throw(
			"Upload <b>Permit Certificate</b> for each permit. Missing: "
			f"<b>{', '.join(missing_certs)}</b>."
		)

	unverified = [
		r.permit_type for r in payable if r.permit_type and not r.get("receipt_verified")
	]
	if unverified:
		fin_seq = get_permit_finance_sequence_for_application(seq)
		fin_name = get_task_name_by_sequence(task.project, fin_seq) if fin_seq else None
		fin_label = (
			frappe.db.get_value("Task", fin_name, "subject") if fin_name else "Finance permit payment"
		)
		frappe.throw(
			f"Finance must tick <b>Receipt Verified</b> on each Local permit (on "
			f"<b>{fin_label}</b>) before completing. Pending: "
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
					"Use the paired finance permit payment task."
				)
		return
	if not is_permit_finance_task_doc(task):
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
	if not is_permit_finance_task_doc(task):
		return False
	if task.status in ("Completed", "Cancelled"):
		return False
	rows = permit_finance_rows(task)
	if not rows:
		# No Local permits — nothing for Finance to pay on this task.
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		PERMIT_JOURNAL_ENTRY_FIELD,
	)

	return all(
		r.get(PERMIT_JOURNAL_ENTRY_FIELD)
		and r.get("payment_receipt")
		and r.get("receipt_verified")
		for r in rows
	)


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
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		sync_project_shipment_status_from_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		apply_finance_payment_to_project_permits,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		refresh_project_documents,
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
		refresh_project_documents(task.project)
		sync_project_shipment_status_from_tasks(task.project)
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{"task": task.name, "status": "Completed", "project": task.project},
	)
	frappe.publish_realtime("cgm_project_tracking_refresh", {"project": task.project})


def _set_permit_register_receipts_verified(task_name: str) -> None:
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
				"Permit Register",
				row.name,
				{"receipt_verified": 1, "status": "Receipt Verified"},
				update_modified=False,
			)


def mark_all_permit_receipts_verified(finance_task_name: str) -> None:
	_set_permit_register_receipts_verified(finance_task_name)
	finance_task = frappe.get_doc("Task", finance_task_name)
	if not finance_task.project:
		return
	app_name = get_permit_application_task_for_finance(finance_task)
	if app_name:
		_set_permit_register_receipts_verified(app_name)


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
	if not is_permit_finance_task_doc(task) or task.status != "Completed":
		return
	app_name = get_permit_application_task_for_finance(task)
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
	if not is_permit_finance_task_doc(task):
		frappe.throw("This action is only for permit finance payment tasks.")

	if task.status == "Completed":
		app_name = get_permit_application_task_for_finance(task) if task.project else None
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

	if not task_has_recorded_payment(task):
		frappe.throw(
			"Record payment via <b>Make Payment</b> (Journal Entry) before verifying receipts."
		)

	sync_permit_invoices_to_finance_task(task, save=True)
	task.reload()

	rows = [r for r in task.get(TASK_PERMITS_FIELD) or [] if r.permit_type]
	if not rows:
		frappe.throw("No permit rows on this task. Refresh the page.")

	missing_receipts = [r.permit_type for r in rows if not r.get("payment_receipt")]
	if missing_receipts:
		app_name = get_permit_application_task_for_finance(task)
		app_label = frappe.db.get_value("Task", app_name, "subject") if app_name else "permit application"
		frappe.throw(
			f"Declarant must upload <b>Payment Receipt</b> on <b>{app_label}</b> first. Missing: "
			f"<b>{', '.join(missing_receipts)}</b>."
		)

	mark_all_permit_receipts_verified(task.name)
	task.reload()
	completed = complete_finance_permit_workflow(task)
	app_name = get_permit_application_task_for_finance(task) if task.project else None
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
	sync_permit_invoices_to_finance_task(task, save=True)
	task.reload()
	completed = auto_complete_finance_permit_task(task)
	app_name = get_permit_application_task_for_finance(task) if task.project else None
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
	missing_payments = [r.permit_type for r in rows if not r.get("journal_entry")]
	return {
		"task_status": task.status,
		"has_payment": task_has_recorded_payment(task),
		"pending_verify": pending_verify,
		"missing_receipts": missing_receipts,
		"missing_payments": missing_payments,
		"ready_to_complete": can_complete_finance_permit_task(task),
	}


# ------------------------------------------------------------------
# Backward-compatible aliases (existing imports / patches)
# ------------------------------------------------------------------

permit_invoices_ready = permit_invoices_submitted
permit_invoices_ready_for_project = project_has_submitted_permit_invoices
try_auto_complete_permit_finance_task = auto_complete_finance_permit_task
get_permit_finance_task = get_finance_permit_task_name


# ============================================================

"""UCR invoice → Finance payment → Declarant receipt → Finance verify → Complete."""
from collections.abc import Callable

from frappe.utils import get_url, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
	UCR_INVOICE_TO_FINANCE,
	UCR_RECEIPT_FOR_DECLARANT,
	UCR_RECEIPT_VERIFY_FINANCE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
	send_notification,
	workflow_notify_message,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
	user_has_finance_department_access,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
	TASK_FINANCE_FIELD,
	get_ucr_invoice_line,
	get_ucr_receipt_line,
	prepare_ucr_task_tables,
	seed_ucr_finance_lines,
	sync_idf_certificate_to_project,
	sync_ucr_finance_lines_to_idf_record,
	ucr_invoice_attached,
	ucr_invoice_verified,
	ucr_receipt_attached,
	ucr_receipt_verified,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
	get_ucr_create_sequence,
	get_ucr_payment_sequence,
	is_ucr_application_task,
	is_ucr_finance_payment_task,
)
# FINANCE_AUDIENCE / DECLARANT_AUDIENCE and the task_sequence /
# get_task_name_by_sequence lookups are already defined at the top of this module
# (this file merges the permit- and UCR-payment workflows); the UCR section below
# reuses them rather than redefining them.


def get_ucr_task(project: str, task_type: str) -> str | None:
	seq_by_type = {
		"create": get_ucr_create_sequence(),
		"payment": get_ucr_payment_sequence(),
	}
	seq = seq_by_type.get(task_type)
	if not seq:
		return None
	return get_task_name_by_sequence(project, seq)


def get_ucr_create_task(project: str) -> str | None:
	return get_ucr_task(project, "create")


def get_ucr_payment_task(project: str) -> str | None:
	return get_ucr_task(project, "payment")


def is_ucr_create_task(task) -> bool:
	return is_ucr_application_task(task_sequence(task))


def is_ucr_payment_task_doc(task) -> bool:
	return is_ucr_finance_payment_task(task_sequence(task))


# ------------------------------------------------------------------
# UCR document state
# ------------------------------------------------------------------


def ucr_invoice_attached_legacy(task) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		TASK_DOCUMENTS_FIELD,
		get_document_type_code,
	)

	legacy = frozenset({"UCR_DOC", "UCR_INV", "UCR Invoice"})
	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		code = get_document_type_code(row.document_type)
		if code in legacy and row.attachment:
			return True
	return False


def ucr_invoice_submitted(task_name: str) -> bool:
	if not task_name or not frappe.db.exists("Task", task_name):
		return False
	if (
		frappe.get_meta("Task").has_field("custom_ucr_invoice_submitted")
		and frappe.db.get_value("Task", task_name, "custom_ucr_invoice_submitted")
	):
		return True
	task = frappe.get_doc("Task", task_name)
	if task.meta.has_field(TASK_FINANCE_FIELD):
		return ucr_invoice_attached(task)
	return ucr_invoice_attached_legacy(task)


def project_has_submitted_ucr_invoice(project: str) -> bool:
	task_name = get_ucr_create_task(project)
	return bool(task_name and ucr_invoice_submitted(task_name))


def idf_certificate_uploaded(task) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_document_type_code,
	)

	for row in task.get("custom_task_documents") or []:
		if get_document_type_code(row.document_type) == "IDF_CERT" and row.attachment:
			return True
	return False


def ucr_invoice_verified_for_create_task(task, finance_task=None) -> bool:
	if task.get("custom_ucr_invoice_verified"):
		return True
	if ucr_invoice_verified(task):
		return True
	if finance_task is None and task.project:
		finance_name = get_ucr_payment_task(task.project)
		finance_task = frappe.get_doc("Task", finance_name) if finance_name else None
	if finance_task:
		fin_inv = get_ucr_invoice_line(finance_task)
		if fin_inv and fin_inv.verified:
			return True
	return False


def ucr_receipt_attached_for_payment_workflow(task) -> bool:
	if ucr_receipt_attached(task) or task.get("custom_ucr_payment_receipt"):
		return True
	if not task.project:
		return False
	app_name = get_ucr_create_task(task.project)
	if not app_name:
		return False
	app = frappe.get_doc("Task", app_name)
	return ucr_receipt_attached(app)


def can_complete_ucr_create_task(task, finance_task=None) -> bool:
	if not is_ucr_create_task(task):
		return False
	if not ucr_invoice_attached(task) and not task.get("custom_ucr_invoice_submitted"):
		return False
	if not ucr_invoice_verified_for_create_task(task, finance_task):
		return False
	if not ucr_receipt_attached(task):
		return False
	return idf_certificate_uploaded(task)


def can_complete_ucr_payment_task(task) -> bool:
	if not is_ucr_payment_task_doc(task):
		return False
	if task.project and not project_has_submitted_ucr_invoice(task.project):
		return False

	inv_ok = ucr_invoice_verified(task) or task.get("custom_ucr_invoice_verified")
	if not inv_ok:
		return False

	rec_ok = ucr_receipt_verified(task) or task.get("custom_ucr_receipt_verified")
	if not rec_ok:
		return False
	return ucr_receipt_attached_for_payment_workflow(task)


# ------------------------------------------------------------------
# Sync / project hooks
# ------------------------------------------------------------------


def run_project_refresh_hooks(project: str) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		sync_project_shipment_status_from_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		refresh_project_documents,
	)

	refresh_project_documents(project)
	sync_project_shipment_status_from_tasks(project)


def sync_ucr_payment_to_idf_record(task) -> None:
	sync_ucr_finance_lines_to_idf_record(task)
	seq = task_sequence(task)
	if is_ucr_payment_task_doc(task) and not frappe.flags.get("cgm_syncing_ucr_receipt"):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			sync_ucr_receipt_verification_to_application_task,
			sync_ucr_verification_to_application_task,
		)

		sync_ucr_verification_to_application_task(task)
		sync_ucr_receipt_verification_to_application_task(task)
	if is_ucr_create_task(task) or is_ucr_payment_task_doc(task):
		sync_idf_certificate_to_project(task)


def sync_ucr_invoice_to_finance_task(project: str) -> str | None:
	finance_name = get_ucr_payment_task(project)
	if not finance_name:
		return None

	finance_task = frappe.get_doc("Task", finance_name)
	prepare_ucr_task_tables(finance_task)
	finance_task.flags.ignore_links = True
	try:
		finance_task.save(ignore_permissions=True)
	finally:
		finance_task.flags.ignore_links = False
	return finance_name


# ------------------------------------------------------------------
# Notifications
# ------------------------------------------------------------------


def _ucr_invoice_pending_finance_notification(task) -> bool:
	"""True when Create UCR has an invoice but Finance has not been notified yet."""
	if not is_ucr_create_task(task):
		return False
	if task.get("custom_ucr_invoice_submitted"):
		return False
	return ucr_invoice_attached(task) or ucr_invoice_attached_legacy(task)


def _notify_finance_for_ucr_invoice(task, *, strict: bool = True) -> dict | None:
	"""Copy invoice to Finance pays UCR and send the finance notification."""
	if not task.project:
		frappe.throw("This task is not linked to a project.")

	finance_task_name = sync_ucr_invoice_to_finance_task(task.project)
	if not finance_task_name:
		msg = (
			"Could not find <b>Finance pays UCR</b> on this project. "
			"Regenerate the sea task plan."
		)
		if strict:
			frappe.throw(msg)
		frappe.msgprint(msg, indicator="orange", alert=True)
		return None

	finance_task = frappe.get_doc("Task", finance_task_name)
	notify_result = send_notification(
		UCR_INVOICE_TO_FINANCE,
		finance_task,
		audience=FINANCE_AUDIENCE,
	)

	return {
		"task": task.name,
		"status": task.status,
		"finance_task": finance_task_name,
		"finance_task_url": get_url(f"/app/task/{finance_task_name}"),
		**notify_result,
		"message": workflow_notify_message(
			"Finance notified on <b>Finance pays UCR</b>. Declarant: upload the IDF/UCR certificate "
			"under <b>Clearance Documents</b> on Create UCR (IDF) when it is issued.",
			notify_result,
			audience=FINANCE_AUDIENCE,
		),
	}


def auto_submit_ucr_invoice_to_finance_if_needed(task) -> dict | None:
	"""On save: notify Finance when the declarant attaches a UCR invoice (no manual submit)."""
	if frappe.flags.get("cgm_auto_submitting_ucr_invoice"):
		return None
	if not _ucr_invoice_pending_finance_notification(task):
		return None

	frappe.flags.cgm_auto_submitting_ucr_invoice = True
	try:
		seed_ucr_finance_lines(task)
		# Do not mark submitted until Finance task is found — otherwise a missing paired
		# task blocks save and the attachment never persists.
		result = _notify_finance_for_ucr_invoice(task, strict=False)
		if not result:
			return None
		if task.meta.has_field("custom_ucr_invoice_submitted"):
			frappe.db.set_value(
				"Task",
				task.name,
				"custom_ucr_invoice_submitted",
				1,
				update_modified=False,
			)
			task.custom_ucr_invoice_submitted = 1
		sync_ucr_finance_lines_to_idf_record(task)
		return result
	finally:
		frappe.flags.cgm_auto_submitting_ucr_invoice = False


@frappe.whitelist()
def submit_ucr_invoice_to_finance(task_name: str) -> dict:
	"""Manual fallback; normal path is auto-submit on invoice attachment."""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_create_task(task):
		frappe.throw("This action is only for <b>Create UCR (IDF)</b> (task 3).")

	seed_ucr_finance_lines(task)
	if not ucr_invoice_attached(task) and not ucr_invoice_attached_legacy(task):
		frappe.throw(
			"Attach the <b>UCR Invoice</b> on <b>Invoices & Receipts</b> before submitting to Finance."
		)

	result = auto_submit_ucr_invoice_to_finance_if_needed(task)
	if result:
		return result

	if task.meta.has_field("custom_ucr_invoice_submitted"):
		task.custom_ucr_invoice_submitted = 1
		task.save(ignore_permissions=True)
	sync_ucr_finance_lines_to_idf_record(task)
	return _notify_finance_for_ucr_invoice(task)


def notify_declarant_upload_ucr_receipt(task) -> dict:
	if not is_ucr_payment_task_doc(task):
		return {"notified": 0}
	if not task_has_recorded_payment(task) or not task.project:
		return {"notified": 0}

	app_name = get_ucr_create_task(task.project)
	if not app_name:
		return {"notified": 0}

	app = frappe.get_doc("Task", app_name)
	seed_ucr_finance_lines(app)
	try:
		app.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="UCR receipt seeding failed",
			message=f"Could not seed UCR finance lines on {app_name}: {frappe.get_traceback()}",
		)

	result = send_notification(
		UCR_RECEIPT_FOR_DECLARANT,
		app,
		audience=DECLARANT_AUDIENCE,
	)
	return {
		**result,
		"application_task": app_name,
		"application_task_url": get_url(f"/app/task/{app_name}"),
		"message": workflow_notify_message(
			"Declarant notified to upload the UCR payment receipt on Create UCR (IDF).",
			result,
			audience=DECLARANT_AUDIENCE,
		),
	}


def notify_finance_verify_ucr_receipt_for_task(task) -> dict:
	if not is_ucr_payment_task_doc(task):
		return {"notified": 0}
	if not ucr_receipt_attached(task) and not task.get("custom_ucr_payment_receipt"):
		return {"notified": 0}

	result = send_notification(
		UCR_RECEIPT_VERIFY_FINANCE,
		task,
		audience=FINANCE_AUDIENCE,
	)
	return {
		**result,
		"message": workflow_notify_message(
			"Finance notified to verify the UCR payment receipt.",
			result,
			audience=FINANCE_AUDIENCE,
		),
	}


@frappe.whitelist()
def notify_finance_verify_ucr_receipt(task_name: str) -> dict:
	if not task_name or not frappe.db.exists("Task", task_name):
		return {"notified": 0}
	task = frappe.get_doc("Task", task_name)
	return notify_finance_verify_ucr_receipt_for_task(task)


def handle_ucr_application_receipt_upload(application_task) -> dict | None:
	if not is_ucr_create_task(application_task) or not application_task.project:
		return None

	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		copy_ucr_receipt_to_finance_task,
		get_ucr_receipt_line,
	)

	app_rec = get_ucr_receipt_line(application_task)
	if not app_rec or not app_rec.attachment:
		return None

	prev = application_task.get_doc_before_save()
	prev_rec = get_ucr_receipt_line(prev) if prev else None
	if prev_rec and prev_rec.attachment == app_rec.attachment:
		return None

	finance_name = copy_ucr_receipt_to_finance_task(application_task)
	if not finance_name:
		return None

	finance_task = frappe.get_doc("Task", finance_name)
	sync_ucr_finance_lines_to_idf_record(finance_task)
	return notify_finance_verify_ucr_receipt_for_task(finance_task)


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------


def validate_ucr_application_not_manually_completed(task) -> None:
	if frappe.flags.get("cgm_auto_completing_sea_task"):
		return
	if not is_ucr_create_task(task):
		return
	if task.status == "Completed" and can_complete_ucr_create_task(task):
		return
	frappe.throw(
		"Complete this task by attaching a verified <b>UCR Invoice</b>, the supplier "
		"<b>UCR Receipt</b>, and the <b>IDF/UCR certificate</b> on this form. "
		"The task will mark itself <b>Completed</b> automatically when all three are in place."
	)


def validate_finance_ucr_payment_task(task) -> None:
	if not is_ucr_payment_task_doc(task):
		return

	app_task = get_ucr_create_task(task.project) if task.project else None
	if app_task and not ucr_invoice_submitted(app_task):
		frappe.throw(
			"The declarant must submit the UCR invoice from <b>Create UCR (IDF)</b> first."
		)

	seed_ucr_finance_lines(task)

	if not (ucr_invoice_verified(task) or task.get("custom_ucr_invoice_verified")):
		frappe.throw(
			"Finance must tick <b>Verified by Finance</b> on the <b>UCR Invoice</b> row."
		)

	task_fields = frappe.get_meta("Task")
	if task_fields.has_field("custom_purchase_invoice") and not task.get("custom_purchase_invoice"):
		frappe.throw("Create and submit a <b>Purchase Invoice</b> from this task before completion.")
	if not task_has_recorded_payment(task):
		frappe.throw(
			"Record payment via <b>Make Payment</b> (Journal Entry) before completion."
		)
	if task.get("custom_payment_entry"):
		pe_status = frappe.db.get_value("Payment Entry", task.custom_payment_entry, "docstatus")
		if int(pe_status or 0) != 1:
			frappe.throw("Payment Entry must be <b>submitted</b> before completing this task.")

	if not (ucr_receipt_attached(task) or task.get("custom_ucr_payment_receipt")):
		frappe.throw(
			"The declarant must attach the <b>UCR Receipt</b> on <b>Create UCR (IDF)</b> before completion."
		)
	if not (ucr_receipt_verified(task) or task.get("custom_ucr_receipt_verified")):
		frappe.throw(
			"Finance must tick <b>Verified by Finance</b> on the <b>UCR Receipt</b> row."
		)


def enforce_ucr_finance_field_permissions(task) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		enforce_finance_line_permissions,
	)

	enforce_finance_line_permissions(task)


# ------------------------------------------------------------------
# Completion
# ------------------------------------------------------------------


def mark_task_completed(task) -> None:
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


def publish_task_completed_event(task) -> None:
	if not task.project:
		return
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{"task": task.name, "status": "Completed", "project": task.project},
	)
	frappe.publish_realtime(
		"cgm_project_tracking_refresh",
		{"project": task.project},
	)


def run_ucr_create_completion_hooks(task) -> None:
	sync_ucr_payment_to_idf_record(task)
	if task.project:
		run_project_refresh_hooks(task.project)
	publish_task_completed_event(task)


def run_ucr_payment_completion_hooks(task) -> None:
	sync_ucr_finance_lines_to_idf_record(task)
	close_ucr_application_when_finance_done(task)
	if task.project:
		run_project_refresh_hooks(task.project)
	publish_task_completed_event(task)


def auto_complete_task_if_ready(
	task,
	*,
	ready_check: Callable,
	completion_hooks: Callable,
) -> bool:
	if task.status in ("Completed", "Cancelled"):
		return False
	if not ready_check(task):
		return False

	frappe.flags.cgm_auto_completing_sea_task = True
	try:
		mark_task_completed(task)
		task.reload()
		completion_hooks(task)
	finally:
		frappe.flags.cgm_auto_completing_sea_task = False
	return True


def try_auto_complete_ucr_create_task(task) -> bool:
	return auto_complete_task_if_ready(
		task,
		ready_check=lambda t: can_complete_ucr_create_task(t),
		completion_hooks=run_ucr_create_completion_hooks,
	)


def try_auto_complete_ucr_payment_task(task) -> bool:
	return auto_complete_task_if_ready(
		task,
		ready_check=can_complete_ucr_payment_task,
		completion_hooks=run_ucr_payment_completion_hooks,
	)


def auto_complete_ucr_application_for_project(project: str) -> bool:
	if not project:
		return False
	app_name = get_ucr_create_task(project)
	if not app_name:
		return False
	app = frappe.get_doc("Task", app_name)
	if app.status in ("Completed", "Cancelled"):
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		sync_ucr_status_from_finance_to_application,
	)

	sync_ucr_status_from_finance_to_application(app)
	app.reload()
	return try_auto_complete_ucr_create_task(app)


def close_ucr_application_when_finance_done(task) -> None:
	if not is_ucr_payment_task_doc(task) or task.status != "Completed" or not task.project:
		return
	auto_complete_ucr_application_for_project(task.project)


@frappe.whitelist()
def ensure_ucr_finance_lines(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		ensure_ucr_finance_lines_saved,
		get_ucr_receipt_line,
	)

	added = ensure_ucr_finance_lines_saved(task)
	return {
		"added": added,
		"has_receipt_row": bool(get_ucr_receipt_line(task)),
		"task": task.name,
	}


@frappe.whitelist()
def get_ucr_declarant_workflow_status(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_create_task(task):
		frappe.throw("This status is only for <b>Create UCR (IDF)</b>.")

	finance_name = get_ucr_payment_task(task.project) if task.project else None
	finance_task = frappe.get_doc("Task", finance_name) if finance_name else None

	if task.status not in ("Completed", "Cancelled") and task.project:
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			sync_ucr_status_from_finance_to_application,
		)

		if sync_ucr_status_from_finance_to_application(task):
			task.reload()
		if can_complete_ucr_create_task(task, finance_task):
			try_auto_complete_ucr_create_task(task)
			task.reload()

	inv = get_ucr_invoice_line(task)
	rec = get_ucr_receipt_line(task)
	fin_inv = get_ucr_invoice_line(finance_task) if finance_task else None
	fin_rec = get_ucr_receipt_line(finance_task) if finance_task else None

	payment_made = bool(finance_task and task_has_recorded_payment(finance_task))

	return {
		"finance_task": finance_name,
		"finance_task_url": get_url(f"/app/task/{finance_name}") if finance_name else None,
		"invoice_submitted": bool(task.get("custom_ucr_invoice_submitted")),
		"invoice_verified": bool(
			(inv and inv.verified)
			or task.get("custom_ucr_invoice_verified")
			or (fin_inv and fin_inv.verified)
		),
		"payment_made": payment_made,
		"receipt_attached": bool((rec and rec.attachment) or (fin_rec and fin_rec.attachment)),
		"receipt_verified": bool(
			(rec and rec.verified)
			or task.get("custom_ucr_receipt_verified")
			or (fin_rec and fin_rec.verified)
		),
		"finance_task_completed": bool(finance_task and finance_task.status == "Completed"),
		"idf_certificate_attached": idf_certificate_uploaded(task),
		"application_ready_to_complete": can_complete_ucr_create_task(task, finance_task),
		"task_status": task.status,
	}


@frappe.whitelist()
def ensure_ucr_finance_task_completed(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This action is only for <b>Finance pays UCR</b>.")
	completed = try_auto_complete_ucr_payment_task(task)
	task.reload()
	return {
		"task": task.name,
		"status": frappe.db.get_value("Task", task.name, "status"),
		"completed": completed,
	}


@frappe.whitelist()
def complete_ucr_finance_task(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This action is only for <b>Finance pays UCR</b>.")
	if not try_auto_complete_ucr_payment_task(task):
		frappe.throw("UCR payment workflow is not finished yet.")
	return {"task": task.name, "status": task.status}


@frappe.whitelist()
def ensure_ucr_invoice_synced(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This action is only for <b>Finance pays UCR</b>.")
	fin_inv = get_ucr_invoice_line(task)
	if fin_inv and fin_inv.attachment:
		return {"synced": False, "message": "UCR invoice already on this task."}
	if not task.project:
		return {"synced": False, "message": "Task has no project."}
	sync_ucr_invoice_to_finance_task(task.project)
	return {"synced": True, "message": "UCR invoice copied from declarant task."}


@frappe.whitelist()
def get_ucr_invoice_preview(task_name: str) -> dict:
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This preview is only for the UCR finance task.")
	if not task.project:
		return {"invoice_url": None, "finance_task": task_name, "finance_task_url": None}

	app_name = get_ucr_create_task(task.project)
	invoice_url = None
	fin_inv = get_ucr_invoice_line(task)
	if fin_inv and fin_inv.attachment:
		invoice_url = fin_inv.attachment
	elif app_name:
		app = frappe.get_doc("Task", app_name)
		inv = get_ucr_invoice_line(app)
		if inv and inv.attachment:
			invoice_url = inv.attachment
		if not invoice_url:
			invoice_url = legacy_ucr_invoice_url(app)

	needs_reload = bool(
		invoice_url and fin_inv and not fin_inv.attachment and app_name
	)

	return {
		"invoice_url": invoice_url,
		"needs_reload": needs_reload,
		"finance_task": task.name,
		"finance_task_url": get_url(f"/app/task/{task.name}"),
		"application_task": app_name,
		"application_task_url": get_url(f"/app/task/{app_name}") if app_name else None,
	}


def legacy_ucr_invoice_url(task) -> str | None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		TASK_DOCUMENTS_FIELD,
		get_document_type_code,
	)

	for row in task.get(TASK_DOCUMENTS_FIELD) or []:
		code = get_document_type_code(row.document_type)
		if code in ("UCR_DOC", "UCR_INV", "UCR Invoice") and row.attachment:
			return row.attachment
	return None


@frappe.whitelist()
def verify_ucr_finance_line(task_name: str, line_type: str = "Invoice") -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	if not user_has_finance_department_access():
		frappe.throw("Only <b>Finance</b> can verify UCR invoice and receipt lines.")

	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This action is only for <b>Finance pays UCR</b>.")

	line_type = (line_type or "Invoice").strip()
	if line_type not in ("Invoice", "Receipt"):
		frappe.throw("Invalid line type.")

	seed_ucr_finance_lines(task)
	line = get_ucr_invoice_line(task) if line_type == "Invoice" else get_ucr_receipt_line(task)
	if not line:
		frappe.throw(f"<b>UCR {line_type}</b> row is missing on this task.")
	if not line.attachment:
		frappe.throw(f"Attach the <b>UCR {line_type}</b> before verifying.")

	line.verified = 1
	line.verified_by = frappe.session.user
	line.verified_on = now_datetime()
	if line_type == "Invoice" and task.meta.has_field("custom_ucr_invoice_verified"):
		task.custom_ucr_invoice_verified = 1
	elif line_type == "Receipt" and task.meta.has_field("custom_ucr_receipt_verified"):
		task.custom_ucr_receipt_verified = 1

	task.save()
	sync_ucr_finance_lines_to_idf_record(task)
	if line_type == "Invoice":
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			sync_ucr_verification_to_application_task,
		)

		sync_ucr_verification_to_application_task(task)
		if task.project:
			auto_complete_ucr_application_for_project(task.project)
	elif line_type == "Receipt":
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			sync_ucr_receipt_verification_to_application_task,
		)

		sync_ucr_receipt_verification_to_application_task(task)
	task.reload()
	completed = try_auto_complete_ucr_payment_task(task)
	label = line.line_label or f"UCR {line_type}"
	return {
		"task": task.name,
		"message": f"<b>{label}</b> verified.",
		"task_status": frappe.db.get_value("Task", task.name, "status"),
		"completed": completed,
	}


# ------------------------------------------------------------------
# Backward-compatible aliases
# ------------------------------------------------------------------

get_ucr_application_task = get_ucr_create_task
get_ucr_finance_task = get_ucr_payment_task
ucr_invoice_ready = ucr_invoice_submitted
ucr_finance_ready_to_complete = can_complete_ucr_payment_task
try_auto_complete_ucr_application_task = try_auto_complete_ucr_create_task
try_auto_complete_ucr_finance_task = try_auto_complete_ucr_payment_task
notify_operations_upload_ucr_receipt = notify_declarant_upload_ucr_receipt
idf_certificate_attached = idf_certificate_uploaded
