"""Workflow gates, UCR and permit payment flows."""
from __future__ import annotations



import frappe

SEA_IMPORT_WORKFLOW_NAME = "CGM Sea Import Workflow"


@frappe.request_cache
def get_workflow_task_gates() -> dict[str, dict]:
	"""Map shipment workflow status → gate row from CGM Shipping Settings."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_cgm_shipping_settings,
	)

	settings = get_cgm_shipping_settings()
	if not settings or not settings.meta.has_field("custom_sea_workflow_task_gates"):
		return {}

	rows = settings.get("custom_sea_workflow_task_gates") or []
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
from frappe.utils import cint, get_url, now_datetime

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
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		get_task_behaviour,
		task_is_permit_application,
	)

	behaviour = get_task_behaviour(task)
	if behaviour.from_template:
		return task_is_permit_application(task) and behaviour.permit_stage == PRE_CLEARANCE_STAGE
	seq = task_sequence(task)
	return is_permit_application_task(seq) and get_permit_stage_for_sequence(seq) == PRE_CLEARANCE_STAGE


def is_pre_clearance_finance_permit_task(task) -> bool:
	return is_permit_finance_task_doc(task)


def is_permit_finance_task_doc(task) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_permit_finance,
	)

	return task_is_permit_finance(task)


def get_permit_application_task_for_finance(finance_task) -> str | None:
	if not finance_task.project:
		return None
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		get_permit_application_for_behaviour,
		get_task_behaviour,
	)

	behaviour = get_task_behaviour(finance_task)
	if behaviour.from_template:
		return get_permit_application_for_behaviour(finance_task)
	app_seq = get_application_sequence_for_finance_task(finance_task)
	if not app_seq:
		return None
	return get_task_name_by_sequence(finance_task.project, app_seq)


def permit_stage_for_finance_task(finance_task) -> str:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		get_task_behaviour,
	)

	behaviour = get_task_behaviour(finance_task)
	if behaviour.from_template and behaviour.permit_stage:
		return behaviour.permit_stage
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_permit_application,
	)

	return task_is_permit_application(task)


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


def task_client_paid_directly(task) -> bool:
	"""Finance marked the client-pays path (no company Journal Entry)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CLIENT_PAID_FIELD,
	)

	return bool(task.get(CLIENT_PAID_FIELD))


def client_paid_settlement_ready(task) -> bool:
	"""Client-pays path is settled when invoices are verified.

	Receipt attachment is optional (keep the field for when one exists).
	Does not require a company Journal Entry / Payment Entry.
	"""
	from frappe.utils import cint

	if not task_client_paid_directly(task):
		return False

	if is_permit_finance_task_doc(task):
		rows = permit_finance_rows(task)
		if not rows:
			return True
		return all(cint(r.get("invoice_verified")) for r in rows)

	# UCR / Entry / Shipping Line / KPA finance lines
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		get_profile_for_sequence,
		invoice_verified,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_ucr_finance_payment_task,
		ucr_invoice_verified,
	)

	seq = task_sequence(task)
	if is_ucr_finance_payment_task(seq) or is_ucr_payment_task_doc(task):
		inv_ok = ucr_invoice_verified(task) or bool(task.get("custom_ucr_invoice_verified"))
		return bool(inv_ok)

	profile = get_profile_for_sequence(seq)
	if profile:
		inv_ok = invoice_verified(task, profile)
		if profile.application_invoice_verified_field:
			inv_ok = inv_ok or bool(task.get(profile.application_invoice_verified_field))
		return bool(inv_ok)

	return True


def task_has_recorded_payment(task) -> bool:
	"""Finance settlement recorded via JE/PE, or client-pays path ready (invoice verified).

	Application-finance tasks with multiple Invoice lines (amendments) require
	every attached invoice line to be settled — not only the task-level JE.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		PERMIT_JOURNAL_ENTRY_FIELD,
	)

	if is_permit_finance_task_doc(task):
		if task_client_paid_directly(task):
			return client_paid_settlement_ready(task)
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
			# Client-pays on a single permit row (amendment after company paid others).
			if cint(row.get("client_reported_paid")) or cint(row.get("client_paid_directly")):
				continue
			return False
		return True

	# Multi-invoice application finance (UCR / Entry / SL / KPA).
	try:
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			all_invoice_lines_settled,
			get_invoice_lines,
			is_application_finance_task,
			profile_for_task,
		)

		profile = profile_for_task(task)
		if profile and is_application_finance_task(
			int(task.get("custom_sequence_no") or 0), profile
		):
			attached = [r for r in get_invoice_lines(task, profile) if r.get("attachment")]
			if len(attached) > 1 or any(cint(r.get("is_amendment")) for r in attached):
				return all_invoice_lines_settled(task, profile)
	except Exception:
		pass

	if task_client_paid_directly(task):
		return client_paid_settlement_ready(task)
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
	"""Each permit row needs verify; JE only on the company-pays path. Receipt is optional."""
	from frappe.utils import cint

	if not is_permit_finance_task_doc(task):
		return
	rows = permit_finance_rows(task)
	if not rows:
		return

	missing_verify = [
		r.permit_type for r in rows if r.permit_type and not cint(r.get("invoice_verified"))
	]
	if missing_verify:
		frappe.throw(
			"Verify each permit invoice before completing. Missing: "
			f"<b>{', '.join(missing_verify)}</b>."
		)

	if task_client_paid_directly(task):
		return

	missing_je = [
		r.permit_type
		for r in rows
		if not r.get("journal_entry")
		and not cint(r.get("client_reported_paid"))
		and not cint(r.get("client_paid_directly"))
	]
	if missing_je:
		frappe.throw(
			"Record a <b>Journal Entry</b> for each permit before completing. Missing: "
			f"<b>{', '.join(missing_je)}</b>. "
			"Or tick <b>Client will pay</b> if the client settles this fee."
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
	"""Fields Declarant owns on the application task (safe to copy → Finance).

	Do not include Finance-owned fields (invoice_verified, journal_entry, receipts).
	Those must be set only on the finance task, or Verify Invoices never appears.
	"""
	return {
		"permit_type": row.get("permit_type"),
		"origin": row.get("origin") or "Local",
		"is_amendment": cint(row.get("is_amendment")),
		"stage": row.get("stage") or PRE_CLEARANCE_STAGE,
		"payment_invoice": row.get("payment_invoice"),
		"invoice_amount": row.get("invoice_amount"),
		"permit_document": row.get("permit_document"),
		"status": row.get("status") or "Invoice Submitted",
		"clearance_phase": row.get("clearance_phase") or "Not Started",
	}


def get_application_permit_rows(application_task_name: str) -> list[dict]:
	fields = [
		"name",
		"permit_type",
		"origin",
		"stage",
		"payment_invoice",
		"invoice_amount",
		"invoice_verified",
		"journal_entry",
		"payment_receipt",
		"permit_document",
		"receipt_verified",
		"status",
		"clearance_phase",
	]
	if frappe.get_meta("Permit Register").has_field("is_amendment"):
		fields.append("is_amendment")
	return frappe.get_all(
		"Permit Register",
		filters={
			"parent": application_task_name,
			"parenttype": "Task",
			"parentfield": TASK_PERMITS_FIELD,
		},
		fields=fields,
		order_by="idx asc",
	)


def _match_finance_permit_row(fin_rows: list, app_row, used: set[int]):
	"""Match application → finance permit row without collapsing amendments by type."""
	ptype = app_row.get("permit_type")
	is_amend = cint(app_row.get("is_amendment"))
	invoice = (app_row.get("payment_invoice") or "").strip()

	# Exact invoice match (same type + amendment flag).
	if invoice:
		for i, fin in enumerate(fin_rows):
			if i in used:
				continue
			if fin.get("permit_type") != ptype:
				continue
			if cint(fin.get("is_amendment")) != is_amend:
				continue
			if (fin.get("payment_invoice") or "").strip() == invoice:
				return i, fin

	# Primary (non-amendment): first unused non-amendment of this type.
	if not is_amend:
		for i, fin in enumerate(fin_rows):
			if i in used:
				continue
			if fin.get("permit_type") == ptype and not cint(fin.get("is_amendment")):
				return i, fin
		return None, None

	# Amendment: unused amendment of same type with no invoice yet.
	for i, fin in enumerate(fin_rows):
		if i in used:
			continue
		if fin.get("permit_type") != ptype or not cint(fin.get("is_amendment")):
			continue
		if not (fin.get("payment_invoice") or "").strip():
			return i, fin
	return None, None


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
	from cgm_shipping.cgm_worldwide_shipping.doctype.permit_register.permit_register import (
		permit_requires_payment,
	)

	added = False
	for row in project.get(PERMIT_REGISTER_FIELD) or []:
		if row.stage != stage or not row.permit_type or not row.get("payment_invoice"):
			continue
		if not permit_requires_payment(row):
			continue
		finance_task.append(
			TASK_PERMITS_FIELD,
			{
				"permit_type": row.permit_type,
				"origin": row.get("origin") or "Local",
				"stage": row.stage,
				"payment_invoice": row.get("payment_invoice"),
				"invoice_amount": row.get("invoice_amount"),
				"invoice_verified": 0,
				"status": "Invoice Submitted",
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


def _apply_permit_row_updates_without_touching_task(
	row_name: str, updates: dict
) -> bool:
	"""Update a Permit Register child row without bumping the parent Task.modified.

	Background finance→declarant mirrors must not invalidate an open form's timestamp.
	"""
	if not row_name or not updates:
		return False
	frappe.db.set_value("Permit Register", row_name, updates, update_modified=False)
	return True


def sync_permit_receipts_to_application_task(finance_task) -> bool:
	"""Mirror Finance-uploaded permit receipts onto the application task for Declarant."""
	if not is_permit_finance_task_doc(finance_task) or not finance_task.project:
		return False
	if frappe.flags.get("cgm_syncing_permit_finance_rows"):
		return False
	app_name = get_permit_application_task_for_finance(finance_task)
	if not app_name:
		return False
	# Do not touch the application task while Complete is in flight (avoids TimestampMismatch).
	if frappe.cache().get_value(f"cgm_complete_permit_app:{app_name}"):
		return False
	app = frappe.get_doc("Task", app_name)
	if not app.meta.has_field(TASK_PERMITS_FIELD):
		return False
	fin_rows = [
		r
		for r in (finance_task.get(TASK_PERMITS_FIELD) or [])
		if r.get("permit_type") and r.get("payment_receipt")
	]
	if not fin_rows:
		return False

	app_by_key = {}
	for r in app.get(TASK_PERMITS_FIELD) or []:
		if not r.get("permit_type"):
			continue
		key = (
			r.permit_type,
			cint(r.get("is_amendment")),
			(r.get("payment_invoice") or ""),
		)
		# Prefer exact invoice keys; keep first primary slot without invoice as fallback.
		app_by_key.setdefault(key, r)
		if not cint(r.get("is_amendment")):
			app_by_key.setdefault((r.permit_type, 0, ""), r)

	changed = False
	needs_insert = False
	for fin_row in fin_rows:
		key = (
			fin_row.permit_type,
			cint(fin_row.get("is_amendment")),
			(fin_row.get("payment_invoice") or ""),
		)
		row = app_by_key.get(key) or (
			None
			if cint(fin_row.get("is_amendment"))
			else app_by_key.get((fin_row.permit_type, 0, ""))
		)
		if not row:
			app.append(TASK_PERMITS_FIELD, build_permit_row_payload(fin_row))
			needs_insert = True
			changed = True
			continue
		updates = {}
		if row.get("payment_receipt") != fin_row.payment_receipt:
			updates["payment_receipt"] = fin_row.payment_receipt
		if cint(fin_row.get("receipt_verified")) and not cint(row.get("receipt_verified")):
			updates["receipt_verified"] = 1
		if fin_row.get("journal_entry") and row.get("journal_entry") != fin_row.journal_entry:
			updates["journal_entry"] = fin_row.journal_entry
		if cint(fin_row.get("invoice_verified")) and not cint(row.get("invoice_verified")):
			updates["invoice_verified"] = 1
		if row.name and _apply_permit_row_updates_without_touching_task(row.name, updates):
			changed = True
	if needs_insert:
		# New rows require a save; avoid bumping modified so open Declarant forms stay savable.
		frappe.flags.cgm_syncing_permit_finance_rows = True
		try:
			app.flags.ignore_links = True
			app.flags.ignore_version = True
			# Persist children then restore the prior modified timestamp.
			prior_modified = frappe.db.get_value("Task", app_name, "modified")
			app.save(ignore_permissions=True)
			if prior_modified:
				frappe.db.set_value(
					"Task",
					app_name,
					"modified",
					prior_modified,
					update_modified=False,
				)
		finally:
			app.flags.ignore_links = False
			frappe.flags.cgm_syncing_permit_finance_rows = False
	elif changed:
		frappe.clear_document_cache("Task", app_name)
	if not changed:
		return False
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{
			"task": app_name,
			"project": finance_task.project,
			"receipt_synced": 1,
			"status": frappe.db.get_value("Task", app_name, "status"),
			# Soft sync: client may refresh fields without treating as hard lock conflict.
			"soft_sync": 1,
		},
	)
	return True


def ensure_finance_permit_receipts_visible_on_application(application_task) -> bool:
	"""On form open: pull Finance receipts onto the Declarant permit application task."""
	if not is_permit_application_task_doc(application_task) or not application_task.project:
		return False
	finance_name = get_finance_permit_task_name(
		application_task.project, task_sequence(application_task)
	)
	if not finance_name:
		return False
	# Cheap SQL gate — avoid loading/saving both tasks when already in sync.
	if not application_missing_finance_permit_receipts(application_task.name, finance_name):
		return False
	return sync_permit_receipts_to_application_task(frappe.get_doc("Task", finance_name))


def stamp_finance_permit_receipts_on_upload(task) -> bool:
	"""Finance upload of a permit receipt is confirmation — auto-stamp verified."""
	if not is_permit_finance_task_doc(task):
		return False
	changed = False
	for row in task.get(TASK_PERMITS_FIELD) or []:
		if row.get("payment_receipt") and not cint(row.get("receipt_verified")):
			row.receipt_verified = 1
			changed = True
	return changed


def handle_finance_permit_receipt_upload(finance_task) -> None:
	"""After Finance attaches permit receipts: stamp verified + show on application task."""
	if not is_permit_finance_task_doc(finance_task):
		return
	stamped = stamp_finance_permit_receipts_on_upload(finance_task)
	if stamped and not frappe.flags.get("cgm_syncing_permit_finance_rows"):
		# Persist stamp without re-entering sync loops.
		for row in finance_task.get(TASK_PERMITS_FIELD) or []:
			if row.name and row.get("payment_receipt") and cint(row.get("receipt_verified")):
				frappe.db.set_value(
					"Permit Register",
					row.name,
					{"receipt_verified": 1},
					update_modified=False,
				)
	sync_permit_receipts_to_application_task(finance_task)


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
	from cgm_shipping.cgm_worldwide_shipping.doctype.permit_register.permit_register import (
		permit_requires_payment,
	)

	# Finance only tracks Local payable invoices; Foreign stays on the application task.
	app_rows = [
		r
		for r in app_rows
		if r.get("permit_type") and r.get("payment_invoice") and permit_requires_payment(r)
	]
	if not app_rows:
		return seed_finance_permit_rows_from_project(finance_task, save=save)

	fin_rows = list(finance_task.get(TASK_PERMITS_FIELD) or [])
	changed = False
	# Drop Foreign / non-payable rows left on the finance task from earlier syncs.
	for fin_row in list(fin_rows):
		if fin_row.permit_type and not permit_requires_payment(fin_row):
			finance_task.remove(fin_row)
			changed = True
	fin_rows = list(finance_task.get(TASK_PERMITS_FIELD) or [])
	used: set[int] = set()

	for row in app_rows:
		data = build_permit_row_payload(row)
		# New invoices always need Finance verification — never inherit verified from app.
		data["invoice_verified"] = 0
		if data.get("status") in (None, "", "Invoice Verified", "Paid", "Receipt Submitted"):
			data["status"] = "Invoice Submitted"
		idx, fin_row = _match_finance_permit_row(fin_rows, row, used)
		if fin_row is not None and idx is not None:
			used.add(idx)
			invoice_changed = (fin_row.get("payment_invoice") or "") != (
				data.get("payment_invoice") or ""
			)
			for key, value in data.items():
				if key == "invoice_verified":
					continue
				if value is not None and fin_row.get(key) != value:
					# Never clear an existing journal_entry via payload (payload omits it).
					fin_row.set(key, value)
					changed = True
			# Replaced invoice on *this* row → must verify again before Make Payment.
			# Amendment rows are separate — do not clear a sibling row's JE.
			if invoice_changed and data.get("payment_invoice"):
				if cint(fin_row.get("invoice_verified")):
					fin_row.invoice_verified = 0
					changed = True
				if fin_row.get("journal_entry"):
					fin_row.journal_entry = None
					changed = True
				if fin_row.get("payment_receipt"):
					fin_row.payment_receipt = None
					fin_row.receipt_verified = 0
					changed = True
				fin_row.status = "Invoice Submitted"
				changed = True
		else:
			finance_task.append(TASK_PERMITS_FIELD, data)
			changed = True
			# Keep fin_rows in sync for subsequent matches in this loop.
			fin_rows = list(finance_task.get(TASK_PERMITS_FIELD) or [])

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


def _reopen_sea_task(task, *, reason: str | None = None) -> bool:
	"""Set a completed sea task back to Open so additional work can continue.

	``cgm_reopening_task`` is set by callers *around* this call to protect later
	saves from flipping status back to Completed — it must not block the reopen
	itself.
	"""
	if not task or task.status != "Completed":
		return False
	if frappe.flags.get("cgm_permit_finance_completing"):
		return False
	values = {
		"status": "Open",
		"progress": 0,
		"completed_by": None,
		"completed_on": None,
	}
	frappe.db.set_value("Task", task.name, values, update_modified=True)
	for field, value in values.items():
		task.set(field, value)
	frappe.clear_document_cache("Task", task.name)
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{
			"task": task.name,
			"status": "Open",
			"project": task.project,
			"reopened": 1,
			"reason": reason or "",
		},
	)
	# set_value bypasses on_update — notify department that work is back.
	try:
		from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
			send_notification,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
			your_turn_notification_for_department,
		)

		notification = your_turn_notification_for_department(task.get("department"))
		if notification:
			send_notification(notification, task, audience=task.get("department") or "users")
	except Exception:
		frappe.log_error(title=f"CGM reopen notify failed for {task.name}")
	return True


def permit_work_fingerprint(task) -> tuple:
	"""Cheap stable fingerprint of permit invoice/payment/receipt state."""
	rows = task.get(TASK_PERMITS_FIELD) or []
	return tuple(
		sorted(
			(
				(r.get("permit_type") or "").strip(),
				(r.get("payment_invoice") or "").strip(),
				(r.get("payment_receipt") or "").strip(),
				cint(r.get("invoice_verified")),
				(r.get("journal_entry") or "").strip(),
				cint(r.get("receipt_verified")),
			)
			for r in rows
			if r.get("permit_type")
		)
	)


def permit_work_changed(task) -> bool:
	"""True when permit rows changed on this save (or there is no prior doc)."""
	prev = task.get_doc_before_save()
	if not prev:
		return True
	return permit_work_fingerprint(task) != permit_work_fingerprint(prev)


def application_missing_finance_permit_receipts(app_name: str, finance_name: str) -> bool:
	"""SQL-only check: Finance has a receipt the application task does not yet mirror."""
	if not app_name or not finance_name:
		return False
	fin_rows = frappe.get_all(
		"Permit Register",
		filters={
			"parent": finance_name,
			"parenttype": "Task",
			"parentfield": TASK_PERMITS_FIELD,
		},
		fields=["permit_type", "payment_receipt"],
		limit_page_length=50,
	)
	fin_receipts = {
		(r.permit_type or "").strip(): (r.payment_receipt or "").strip()
		for r in fin_rows
		if r.permit_type and r.payment_receipt
	}
	if not fin_receipts:
		return False
	app_rows = frappe.get_all(
		"Permit Register",
		filters={
			"parent": app_name,
			"parenttype": "Task",
			"parentfield": TASK_PERMITS_FIELD,
		},
		fields=["permit_type", "payment_receipt"],
		limit_page_length=50,
	)
	app_receipts = {
		(r.permit_type or "").strip(): (r.payment_receipt or "").strip()
		for r in app_rows
		if r.permit_type
	}
	for permit_type, receipt in fin_receipts.items():
		if app_receipts.get(permit_type) != receipt:
			return True
	return False


def permit_finance_rows_needing_work(finance_task) -> list:
	"""Local permit rows that still need invoice verify or payment (receipt is optional)."""
	pending = []
	client_paid = task_client_paid_directly(finance_task)
	for row in permit_finance_rows(finance_task):
		if not row.get("payment_invoice"):
			continue
		if not cint(row.get("invoice_verified")):
			pending.append(row)
			continue
		if not client_paid and not row.get("journal_entry"):
			pending.append(row)
	return pending


def reopen_permit_finance_if_pending_work(finance_task) -> dict | None:
	"""Reopen a Completed finance permit task when unpaid / unverified rows exist.

	Covers the case where additional permits were synced onto Finance after it
	was already completed (Make Payment is hidden while status is Completed).
	"""
	if frappe.flags.get("cgm_reopening_task") or frappe.flags.get("cgm_permit_finance_completing"):
		return None
	if not is_permit_finance_task_doc(finance_task):
		return None
	if finance_task.status == "Cancelled":
		return None

	pending = permit_finance_rows_needing_work(finance_task)
	if not pending:
		return None
	if finance_task.status != "Completed":
		return {
			"reopened": [],
			"pending_permits": [r.permit_type for r in pending if r.permit_type],
			"finance_task": finance_task.name,
		}

	reopened: list[str] = []
	frappe.flags.cgm_reopening_task = True
	try:
		if _reopen_sea_task(
			finance_task,
			reason="Additional permit invoices need verification and payment",
		):
			reopened.append(finance_task.name)
			finance_task.status = "Open"
			finance_task.progress = 0
			finance_task.completed_by = None
			finance_task.completed_on = None
		app_name = get_permit_application_task_for_finance(finance_task)
		if app_name:
			app = frappe.get_doc("Task", app_name)
			if app.status == "Completed" and _reopen_sea_task(
				app,
				reason="Additional permits pending Finance payment",
			):
				reopened.append(app_name)
	finally:
		frappe.flags.cgm_reopening_task = False

	return {
		"reopened": reopened,
		"pending_permits": [r.permit_type for r in pending if r.permit_type],
		"finance_task": finance_task.name,
		"finance_task_url": get_url(f"/app/task/{finance_task.name}"),
		"message": (
			f"Reopened for unpaid permits: "
			f"<b>{', '.join(r.permit_type for r in pending if r.permit_type)}</b>."
		),
	}


@frappe.whitelist()
def reopen_permit_finance_for_pending_payments(task_name: str) -> dict:
	"""Reopen Finance pays … Permits when unpaid/unverified rows exist after completion."""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	if not is_permit_finance_task_doc(task):
		frappe.throw("This action is only for Finance permit payment tasks.")
	sync_permit_invoices_to_finance_task(task, save=True)
	task.reload()
	result = reopen_permit_finance_if_pending_work(task) or {}
	task.reload()
	pending = permit_finance_rows_needing_work(task)
	return {
		"task": task.name,
		"status": task.status,
		"pending_permits": [r.permit_type for r in pending if r.permit_type],
		**result,
	}


def handle_additional_permit_work_on_application(application_task) -> dict | None:
	"""When Declarant adds more permit invoices (even after completion), reopen finance.

	Also reopens the application task so certificates / further permits can continue.
	"""
	if frappe.flags.get("cgm_reopening_task") or frappe.flags.get("cgm_permit_finance_completing"):
		return None
	if not is_permit_application_task_doc(application_task) or not application_task.project:
		return None
	# Skip heavy sync/reopen when permit rows did not change on this save.
	if application_task.get_doc_before_save() and not permit_work_changed(application_task):
		return None

	finance_name = get_finance_permit_task_name(
		application_task.project, task_sequence(application_task)
	)
	if not finance_name:
		return None

	finance_task = frappe.get_doc("Task", finance_name)
	sync_permit_invoices_to_finance_task(finance_task, save=True)
	finance_task.reload()

	pending = permit_finance_rows_needing_work(finance_task)
	if not pending:
		return None

	reopened: list[str] = []
	frappe.flags.cgm_reopening_task = True
	try:
		if _reopen_sea_task(
			finance_task,
			reason="Additional permit invoices need verification and payment",
		):
			reopened.append(finance_name)
			finance_task.reload()
		if application_task.status == "Completed" and _reopen_sea_task(
			application_task,
			reason="Additional permits / documents added after prior completion",
		):
			reopened.append(application_task.name)
			application_task.status = "Open"
			application_task.progress = 0
			application_task.completed_by = None
			application_task.completed_on = None
	finally:
		frappe.flags.cgm_reopening_task = False

	unverified = [
		r.permit_type for r in pending if r.permit_type and not cint(r.get("invoice_verified"))
	]
	notify_result = {"notified": 0}
	# Notify only when we actually reopened (avoid spam on every incidental save).
	if unverified and reopened:
		notify_result = send_notification(
			PERMIT_INVOICES_TO_FINANCE,
			finance_task,
			audience=FINANCE_AUDIENCE,
		)
		if application_task.meta.has_field("custom_permit_invoices_submitted"):
			frappe.db.set_value(
				"Task",
				application_task.name,
				"custom_permit_invoices_submitted",
				1,
				update_modified=False,
			)
			application_task.custom_permit_invoices_submitted = 1

	return {
		"reopened": reopened,
		"pending_permits": [r.permit_type for r in pending if r.permit_type],
		"finance_task": finance_name,
		"finance_task_url": get_url(f"/app/task/{finance_name}"),
		**notify_result,
		"message": workflow_notify_message(
			(
				f"Additional permit work reopened <b>{', '.join(reopened) or finance_name}</b>. "
				f"Pending: <b>{', '.join(r.permit_type for r in pending if r.permit_type)}</b>."
			),
			notify_result,
			audience=FINANCE_AUDIENCE,
		),
	}


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


def notify_finance_upload_permit_receipts(task) -> dict:
	"""After Journal Entry payment: prompt Upload Receipt owners (Settings → Declaration)."""
	if not is_permit_finance_payment_task(task_sequence(task)):
		return {"notified": 0}
	if not task_has_recorded_payment(task):
		return {"notified": 0}
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		FLOW_PERMIT,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
		audience_label_for_receipt_upload,
	)

	audience = audience_label_for_receipt_upload(FLOW_PERMIT)
	result = send_notification(
		PERMIT_RECEIPTS_FOR_DECLARANT,
		task,
		audience=audience,
	)
	return {
		**result,
		"task": task.name,
		"task_url": get_url(f"/app/task/{task.name}"),
		"message": workflow_notify_message(
			f"{audience} notified to attach permit payment receipts when available.",
			result,
			audience=audience,
		),
	}


# Alias: Settings assign Upload Receipt to Declaration (Declarant).
notify_declarant_upload_permit_receipts = notify_finance_upload_permit_receipts


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


def permit_application_client_paid(task) -> bool:
	"""True when Finance confirmed the client settled the paired permit payment."""
	if task_client_paid_directly(task):
		return True
	if not task.project:
		return False
	fin_name = get_finance_permit_task_name(task.project, task_sequence(task))
	if not fin_name:
		return False
	return task_client_paid_directly(frappe.get_doc("Task", fin_name))


def validate_permit_application_can_complete(task) -> None:
	if frappe.flags.get("cgm_auto_completing_sea_task"):
		return
	seq = task_sequence(task)
	if not is_permit_application_task(seq):
		return

	# Client-pays path still needs invoices submitted + Finance settlement (verify +
	# client receipt) + certificates. Only the company Journal Entry is skipped.
	if permit_application_client_paid(task):
		payable = payable_permit_rows(task)
		if payable and not task.get("custom_permit_invoices_submitted"):
			frappe.throw(
				"Attach all <b>Local</b> permit invoices and save — Finance is notified "
				"automatically — before completing this task."
			)
		if payable and not finance_payment_completed(task.project, seq):
			fin_seq = get_permit_finance_sequence_for_application(seq)
			fin_name = get_task_name_by_sequence(task.project, fin_seq) if fin_seq else None
			fin_label = (
				frappe.db.get_value("Task", fin_name, "subject")
				if fin_name
				else "Finance permit payment"
			)
			frappe.throw(
				f"Finance must verify invoices, tick <b>Client will pay</b>, and upload the "
				f"client's receipt on <b>{fin_label}</b> before this task can be completed."
			)
		rows = [r for r in (task.get(TASK_PERMITS_FIELD) or []) if r.get("permit_type")]
		missing_certs = [r.permit_type for r in rows if not r.get("permit_document")]
		if missing_certs:
			frappe.throw(
				"Upload <b>Permit Certificate</b> for each permit. Missing: "
				f"<b>{', '.join(missing_certs)}</b>."
			)
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

	missing_certs = [r.permit_type for r in rows if r.permit_type and not r.get("permit_document")]
	if missing_certs:
		frappe.throw(
			"Upload <b>Permit Certificate</b> for each permit. Missing: "
			f"<b>{', '.join(missing_certs)}</b>."
		)
	# Payment receipt is optional — Finance settlement (JE / Client will pay) is enough.


def enforce_receipt_verified_permission(task) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		ACTION_UPLOAD_RECEIPT,
		ACTION_VERIFY_INVOICE,
		FLOW_PERMIT,
		user_has_responsibility,
	)

	if is_permit_application_task_doc(task):
		# Application task mirrors Finance ticks — only responsibility holders may change them.
		for row in task.get(TASK_PERMITS_FIELD) or []:
			if row.get("receipt_verified") and not user_has_responsibility(
				FLOW_PERMIT, ACTION_UPLOAD_RECEIPT
			):
				frappe.throw(
					"Only the configured <b>Upload Receipt</b> role group can mark "
					"<b>Receipt Verified</b>. Use the paired finance permit payment task "
					"(CGM Shipping Settings → Document responsibilities)."
				)
			if _permit_invoice_verified_changed(task, row) and not user_has_responsibility(
				FLOW_PERMIT, ACTION_VERIFY_INVOICE
			):
				frappe.throw(
					"Only the configured <b>Verify Invoice</b> role group can mark "
					"<b>Invoice Verified</b>. Use the paired finance permit payment task "
					"(CGM Shipping Settings → Document responsibilities)."
				)
		return
	if not is_permit_finance_task_doc(task):
		return
	for row in task.get(TASK_PERMITS_FIELD) or []:
		if row.get("receipt_verified") and not user_has_responsibility(
			FLOW_PERMIT, ACTION_UPLOAD_RECEIPT
		):
			frappe.throw(
				"Only the configured <b>Upload Receipt</b> role group can mark "
				"<b>Receipt Verified</b> on permit rows "
				"(CGM Shipping Settings → Document responsibilities)."
			)
		if _permit_invoice_verified_changed(task, row) and not user_has_responsibility(
			FLOW_PERMIT, ACTION_VERIFY_INVOICE
		):
			frappe.throw(
				"Only the configured <b>Verify Invoice</b> role group can mark "
				"<b>Invoice Verified</b> on permit rows "
				"(CGM Shipping Settings → Document responsibilities)."
			)


def _permit_invoice_verified_changed(task, row) -> bool:
	"""True when Invoice Verified was newly ticked on this save."""
	if not cint(row.get("invoice_verified")):
		return False
	prev = task.get_doc_before_save()
	if not prev:
		return True
	prev_row = None
	for candidate in prev.get(TASK_PERMITS_FIELD) or []:
		if candidate.name == row.name or (
			candidate.get("permit_type") and candidate.permit_type == row.get("permit_type")
		):
			prev_row = candidate
			break
	return not cint(prev_row.get("invoice_verified") if prev_row else 0)


# ------------------------------------------------------------------
# Completion
# ------------------------------------------------------------------


def can_complete_finance_permit_task(task) -> bool:
	from frappe.utils import cint

	if not is_permit_finance_task_doc(task):
		return False
	if task.status in ("Completed", "Cancelled"):
		return False
	rows = permit_finance_rows(task)
	if not rows:
		# No Local permits — nothing for Finance to pay on this task.
		return False
	if task_client_paid_directly(task):
		return all(cint(r.get("invoice_verified")) for r in rows)
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		PERMIT_JOURNAL_ENTRY_FIELD,
	)

	return all(r.get(PERMIT_JOURNAL_ENTRY_FIELD) for r in rows)


def mark_permit_task_completed(task) -> None:
	mark_task_completed(task)


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
	# Client-paid: leave the application task open so the declarant can attach
	# certificates (if any) and mark it complete themselves.
	if task_client_paid_directly(task):
		return
	app_name = get_permit_application_task_for_finance(task)
	if not app_name:
		return
	if frappe.db.get_value("Task", app_name, "status") == "Completed":
		return
	# Do not force-complete while Local permits still lack certificates / receipts,
	# or while Finance still has unpaid rows (should not happen when finance is Completed).
	app = frappe.get_doc("Task", app_name)
	merge_project_permits_into_application_task(app)
	try:
		validate_permit_application_can_complete(app)
	except frappe.ValidationError:
		return
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
def verify_all_permit_invoices(task_name: str) -> dict:
	"""Finance: mark all Local permit invoices verified on the finance payment task."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		ACTION_VERIFY_INVOICE,
		FLOW_PERMIT,
		throw_unless_responsibility,
	)

	throw_unless_responsibility(FLOW_PERMIT, ACTION_VERIFY_INVOICE, label="verify permit invoices")

	task = frappe.get_doc("Task", task_name)
	if not is_permit_finance_task_doc(task):
		frappe.throw("This action is only for permit finance payment tasks.")

	sync_permit_invoices_to_finance_task(task, save=True)
	task.reload()

	rows = permit_finance_rows(task)
	if not rows:
		frappe.throw(
			"No Local permit invoices to verify on this task (Foreign permits skip payment)."
		)

	missing_invoices = [r.permit_type for r in rows if not r.get("payment_invoice")]
	if missing_invoices:
		frappe.throw(
			"Declarant must attach <b>Permit Invoice</b> first. Missing: "
			f"<b>{', '.join(missing_invoices)}</b>."
		)

	verified = 0
	for row in rows:
		if not cint(row.get("invoice_verified")):
			frappe.db.set_value(
				"Permit Register",
				row.name,
				{"invoice_verified": 1, "status": "Invoice Verified"},
				update_modified=False,
			)
			verified += 1
		elif row.name:
			frappe.db.set_value(
				"Permit Register",
				row.name,
				{"status": "Invoice Verified"},
				update_modified=False,
			)

	task.reload()
	sync_permit_invoice_verification_to_application(task)
	sync_task_permits_to_project(task)

	return {
		"task": task.name,
		"verified": verified,
		"message": (
			f"Verified <b>{verified}</b> permit invoice(s). You can now use <b>Make Payment</b>."
			if verified
			else "All permit invoices are already verified. You can use <b>Make Payment</b>."
		),
	}


def sync_permit_invoice_verification_to_application(finance_task) -> bool:
	"""Mirror Finance invoice_verified onto the application task for Declarant visibility."""
	if not is_permit_finance_task_doc(finance_task) or not finance_task.project:
		return False
	app_name = get_permit_application_task_for_finance(finance_task)
	if not app_name:
		return False
	app = frappe.get_doc("Task", app_name)
	if not app.meta.has_field(TASK_PERMITS_FIELD):
		return False
	fin_by_type = {
		r.permit_type: r
		for r in (finance_task.get(TASK_PERMITS_FIELD) or [])
		if r.get("permit_type") and cint(r.get("invoice_verified"))
	}
	if not fin_by_type:
		return False
	changed = False
	for row in app.get(TASK_PERMITS_FIELD) or []:
		fin_row = fin_by_type.get(row.permit_type)
		if not fin_row or not row.name:
			continue
		updates = {}
		if not cint(row.get("invoice_verified")):
			updates["invoice_verified"] = 1
		if row.get("status") in (None, "", "Invoice Submitted"):
			updates["status"] = "Invoice Verified"
		if _apply_permit_row_updates_without_touching_task(row.name, updates):
			changed = True
	if not changed:
		return False
	frappe.clear_document_cache("Task", app_name)
	frappe.publish_realtime(
		"cgm_task_status_changed",
		{"task": app_name, "project": finance_task.project, "soft_sync": 1},
	)
	return True


@frappe.whitelist()
def complete_permit_application_task(task_name: str) -> dict:
	"""Complete a permit application task from a fresh DB load (avoids stale-form timestamp conflicts)."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw("Task not found.")
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)

	# Serialize completion so a form save / soft-sync cannot collide mid-request.
	lock_key = f"cgm_complete_permit_app:{task_name}"
	if frappe.cache().get_value(lock_key):
		frappe.throw(
			"This task is already being completed. Wait a moment, then refresh.",
			title="Please wait",
		)
	frappe.cache().set_value(lock_key, 1, expires_in_sec=30)
	try:
		task = frappe.get_doc("Task", task_name)
		if not is_permit_application_task_doc(task):
			frappe.throw("This action is only for pre-/post-clearance permit application tasks.")
		if task.status == "Cancelled":
			frappe.throw("Cancelled tasks cannot be completed.")
		if task.status == "Completed":
			return {"task": task.name, "status": "Completed", "already_completed": 1}

		# In-memory only — do not nested-save before the completion save (avoids concurrent locks).
		merge_project_permits_into_application_task(task, save=False)

		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			validate_permit_application_task,
		)

		seq = task_sequence(task)
		validate_permit_application_task(task, seq)
		validate_permit_application_can_complete(task)

		task.status = "Completed"
		task.completed_by = frappe.session.user
		task.completed_on = now_datetime()
		task.progress = 100
		frappe.flags.cgm_auto_completing_sea_task = True
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_auto_completing_sea_task = False

		# Defer realtime so the client is not mid-reload while this request finishes.
		frappe.publish_realtime(
			"cgm_task_status_changed",
			{"task": task.name, "status": "Completed", "project": task.project},
			after_commit=True,
		)
		return {
			"task": task.name,
			"status": "Completed",
			"message": "Permit application task completed.",
		}
	finally:
		frappe.cache().delete_value(lock_key)


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

	# Only Local (payable) permits need payment receipts — Foreign uses certificate only.
	rows = permit_finance_rows(task)
	if not rows:
		frappe.throw(
			"No Local permit rows need receipt verification on this task "
			"(Foreign permits skip payment)."
		)

	missing_receipts = [r.permit_type for r in rows if not r.get("payment_receipt")]
	if missing_receipts:
		frappe.throw(
			"Finance must upload <b>Payment Receipt</b> on this finance task first. Missing: "
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
	rows = permit_finance_rows(task)
	pending_verify = [
		r.permit_type for r in rows if r.get("payment_invoice") and not cint(r.get("invoice_verified"))
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		ROLE_APPLICATION,
		ROLE_FINANCE_PAYMENT,
		task_has_behaviour_fields,
	)

	if task_has_behaviour_fields():
		role = ROLE_APPLICATION if task_type == "create" else ROLE_FINANCE_PAYMENT
		name = frappe.db.get_value(
			"Task",
			{
				"project": project,
				"custom_task_role": role,
				"custom_payment_kind": "UCR",
			},
			"name",
			order_by="custom_sequence_no asc",
		)
		if name:
			return name

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
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_application,
	)

	return task_is_ucr_application(task)


def is_ucr_payment_task_doc(task) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		task_is_ucr_finance,
	)

	return task_is_ucr_finance(task)


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
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		IDF_CERTIFICATE_CODES,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		primary_attachment,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_document_type_code,
		get_stamped_required_document_types,
		stamped_required_document_types_attached,
	)

	# Prefer template stamp (handles "IDF CERT" vs "IDF_CERT" and draft/final slots).
	if get_stamped_required_document_types(task):
		return stamped_required_document_types_attached(task)

	for row in task.get("custom_task_documents") or []:
		if get_document_type_code(row.document_type) in IDF_CERTIFICATE_CODES and primary_attachment(
			row
		):
			return True
	return False


def ucr_invoice_verified_for_create_task(task, finance_task=None) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		all_invoice_lines_verified,
		get_invoice_lines,
	)

	profile = APPLICATION_FINANCE_PROFILES["UCR Application"]
	rows = [r for r in get_invoice_lines(task, profile) if r.get("attachment")]
	if len(rows) > 1 or any(cint(r.get("is_amendment")) for r in rows):
		if not all_invoice_lines_verified(task, profile):
			return False
		if finance_task is None and task.project:
			finance_name = get_ucr_payment_task(task.project)
			finance_task = frappe.get_doc("Task", finance_name) if finance_name else None
		if finance_task:
			fin_rows = [r for r in get_invoice_lines(finance_task, profile) if r.get("attachment")]
			if fin_rows and not all_invoice_lines_verified(finance_task, profile):
				return False
		return True

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
	if finance_task is None and task.project:
		finance_name = get_ucr_finance_task(task.project)
		finance_task = frappe.get_doc("Task", finance_name) if finance_name else None
	# Client-pays and company-pays: Create UCR still needs invoice verified + certificate docs.
	# Receipt stays on Finance. Certificate gate prefers template stamp when present.
	if not ucr_invoice_attached(task) and not task.get("custom_ucr_invoice_submitted"):
		return False
	if not ucr_invoice_verified_for_create_task(task, finance_task):
		return False
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_stamped_required_document_types,
		stamped_required_document_types_attached,
	)

	if get_stamped_required_document_types(task):
		return stamped_required_document_types_attached(task)
	return idf_certificate_uploaded(task)


def can_complete_ucr_payment_task(task) -> bool:
	if not is_ucr_payment_task_doc(task):
		return False
	# Prefer the shared multi-invoice application-finance gate (primary + amendments).
	try:
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			APPLICATION_FINANCE_PROFILES,
			can_complete_application_finance_task,
		)

		return can_complete_application_finance_task(
			task, APPLICATION_FINANCE_PROFILES["UCR Application"]
		)
	except Exception:
		pass

	if task_client_paid_directly(task):
		if not client_paid_settlement_ready(task):
			return False
	else:
		if task.project and not project_has_submitted_ucr_invoice(task.project):
			return False

		inv_ok = ucr_invoice_verified(task) or task.get("custom_ucr_invoice_verified")
		if not inv_ok:
			return False

		if not task_has_recorded_payment(task):
			return False

	# UCR always requires receipt attach + verify (Entry Slip is the optional-receipt exception).
	if not ucr_receipt_attached_for_payment_workflow(task):
		return False
	if not (ucr_receipt_verified(task) or task.get("custom_ucr_receipt_verified")):
		return False
	return True


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
	# Do not touch a settled finance task — incidental saves were overwriting
	# Completed back to Open when a stale in-memory Open doc raced the write.
	if finance_task.status == "Completed":
		return finance_name
	prepare_ucr_task_tables(finance_task)
	finance_task.flags.ignore_links = True
	try:
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			preserve_completed_status_against_stale_save,
		)

		preserve_completed_status_against_stale_save(finance_task)
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


def notify_finance_upload_ucr_receipt(task) -> dict:
	"""After Journal Entry payment: prompt Upload Receipt owners (Settings → Declaration)."""
	if not is_ucr_payment_task_doc(task):
		return {"notified": 0}
	if not task_has_recorded_payment(task):
		return {"notified": 0}

	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		FLOW_UCR,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
		audience_label_for_receipt_upload,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import seed_ucr_finance_lines

	seed_ucr_finance_lines(task)
	try:
		task.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="UCR receipt seeding failed",
			message=f"Could not seed UCR finance lines on {task.name}: {frappe.get_traceback()}",
		)

	audience = audience_label_for_receipt_upload(FLOW_UCR)
	result = send_notification(
		UCR_RECEIPT_FOR_DECLARANT,
		task,
		audience=audience,
	)
	return {
		**result,
		"task": task.name,
		"task_url": get_url(f"/app/task/{task.name}"),
		"message": workflow_notify_message(
			f"{audience} notified to attach the UCR Receipt when available.",
			result,
			audience=audience,
		),
	}


# Alias: Settings assign UCR Upload Receipt to Declaration (Declarant).
notify_declarant_upload_ucr_receipt = notify_finance_upload_ucr_receipt
notify_operations_upload_ucr_receipt = notify_finance_upload_ucr_receipt


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
	"""Legacy path: sync an existing Create UCR receipt onto Finance pays UCR."""
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


def handle_ucr_finance_receipt_upload(finance_task) -> dict | None:
	"""When Finance attaches a UCR receipt: auto-confirm, mirror to Declarant, sync IDF."""
	if not is_ucr_payment_task_doc(finance_task) or not finance_task.project:
		return None

	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		copy_ucr_receipt_to_application_task,
		get_ucr_receipt_line,
	)
	from frappe.utils import cint

	fin_rec = get_ucr_receipt_line(finance_task)
	if not fin_rec or not fin_rec.attachment:
		return None

	prev = finance_task.get_doc_before_save()
	prev_rec = get_ucr_receipt_line(prev) if prev else None
	attachment_changed = not (prev_rec and prev_rec.attachment == fin_rec.attachment)

	# Upload itself confirms the receipt — no separate verify step.
	if fin_rec.name and not cint(fin_rec.verified):
		frappe.db.set_value(
			"Task Finance Line",
			fin_rec.name,
			{
				"verified": 1,
				"verified_by": frappe.session.user,
				"verified_on": now_datetime(),
			},
			update_modified=False,
		)
		if finance_task.meta.has_field("custom_ucr_receipt_verified"):
			frappe.db.set_value(
				"Task", finance_task.name, "custom_ucr_receipt_verified", 1, update_modified=False
			)
		finance_task.reload()

	copy_ucr_receipt_to_application_task(finance_task)
	sync_ucr_finance_lines_to_idf_record(finance_task)
	if attachment_changed:
		app_name = get_ucr_create_task(finance_task.project)
		if app_name:
			frappe.publish_realtime(
				"cgm_task_status_changed",
				{
					"task": app_name,
					"project": finance_task.project,
					"receipt_synced": 1,
					"soft_sync": 1,
				},
			)
	return None


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
		"Complete this task by attaching a verified <b>UCR Invoice</b> and the "
		"<b>IDF/UCR certificate</b> on this form. Finance uploads the <b>UCR Receipt</b> "
		"after payment. The task will mark itself <b>Completed</b> automatically when "
		"requirements are in place."
	)


def validate_finance_ucr_payment_task(task) -> None:
	if not is_ucr_payment_task_doc(task):
		return

	# Client-pays path: verify invoice; receipt still required for UCR (unlike Entry Slip).
	if task_client_paid_directly(task):
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
		if not client_paid_settlement_ready(task):
			frappe.throw(
				"Client-pays path is not complete: verify the invoice first."
			)
		if not ucr_receipt_attached_for_payment_workflow(task):
			frappe.throw(
				"Attach the <b>UCR Receipt</b> before completing this task."
			)
		if not (ucr_receipt_verified(task) or task.get("custom_ucr_receipt_verified")):
			frappe.throw(
				"Finance must tick <b>Verified by Finance</b> on the <b>UCR Receipt</b> row "
				"before completing this task."
			)
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

	if not task_has_recorded_payment(task):
		frappe.throw(
			"Record payment via <b>Make Payment</b> (Journal Entry) before completion, "
			"or tick <b>Client will pay</b> if the client settles it."
		)
	if task.get("custom_payment_entry"):
		pe_status = frappe.db.get_value("Payment Entry", task.custom_payment_entry, "docstatus")
		if int(pe_status or 0) != 1:
			frappe.throw("Payment Entry must be <b>submitted</b> before completing this task.")
	if not ucr_receipt_attached_for_payment_workflow(task):
		frappe.throw(
			"Attach the <b>UCR Receipt</b> after payment before completing this task."
		)
	if not (ucr_receipt_verified(task) or task.get("custom_ucr_receipt_verified")):
		frappe.throw(
			"Finance must tick <b>Verified by Finance</b> on the <b>UCR Receipt</b> row "
			"before completing this task."
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
	"""Persist Completed and keep the in-memory doc in sync.

	Only updating via set_value left callers holding status=Open; a later
	task.save() then overwrote Completed and made List View show Open while
	the form (after reload) still looked Completed.
	"""
	completed_by = task.completed_by or frappe.session.user
	completed_on = task.completed_on or now_datetime()
	values = {
		"status": "Completed",
		"completed_by": completed_by,
		"completed_on": completed_on,
		"progress": 100,
	}
	if task.name and frappe.db.exists("Task", task.name):
		frappe.db.set_value("Task", task.name, values, update_modified=True)
		frappe.clear_document_cache("Task", task.name)
	for field, value in values.items():
		task.set(field, value)
	# Push list/form to the same status immediately (avoids stale Open in list).
	publish_task_completed_event(task)


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
		"client_paid_directly": bool(
			finance_task and task_client_paid_directly(finance_task)
		),
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
def verify_ucr_finance_line(
	task_name: str,
	line_type: str = "Invoice",
	finance_line_name: str | None = None,
	attachment: str | None = None,
) -> dict:
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		ACTION_VERIFY_INVOICE,
		FLOW_UCR,
		throw_unless_responsibility,
	)

	throw_unless_responsibility(FLOW_UCR, ACTION_VERIFY_INVOICE, label="verify UCR invoice and receipt lines")

	task = frappe.get_doc("Task", task_name)
	if not is_ucr_payment_task_doc(task):
		frappe.throw("This action is only for <b>Finance pays UCR</b>.")

	line_type = (line_type or "Invoice").strip()
	if line_type not in ("Invoice", "Receipt"):
		frappe.throw("Invalid line type.")

	seed_ucr_finance_lines(task)
	if line_type == "Invoice":
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			get_invoice_lines,
			profile_for_task,
			all_invoice_lines_verified,
		)

		profile = profile_for_task(task)
		line = None
		if finance_line_name and profile:
			for row in get_invoice_lines(task, profile):
				if row.name == finance_line_name:
					line = row
					break
		if not line and profile:
			for row in get_invoice_lines(task, profile):
				if row.get("attachment") and not cint(row.get("verified")):
					line = row
					break
		if not line:
			line = get_ucr_invoice_line(task)
	else:
		line = get_ucr_receipt_line(task)
		if finance_line_name and line and line.name != finance_line_name:
			for row in task.get(TASK_FINANCE_FIELD) or []:
				if row.name == finance_line_name and (row.line_type or "") == "Receipt":
					line = row
					break
	if not line:
		frappe.throw(f"<b>UCR {line_type}</b> row is missing on this task.")
	# Desk often shows an attach before the child row is persisted (soft-sync /
	# skipped autosave). Accept the URL from the form so Verify still works.
	pending_attachment = (attachment or "").strip()
	if not line.attachment and pending_attachment:
		line.attachment = pending_attachment
	if not line.attachment:
		frappe.throw(f"Attach the <b>UCR {line_type}</b> before verifying.")

	line.verified = 1
	line.verified_by = frappe.session.user
	line.verified_on = now_datetime()
	if line_type == "Invoice" and task.meta.has_field("custom_ucr_invoice_verified"):
		from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
			all_invoice_lines_verified,
			profile_for_task,
		)

		profile = profile_for_task(task)
		if not profile or all_invoice_lines_verified(task, profile):
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
