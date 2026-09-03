"""
Sea Freight Clearance - ordered task plan and workflow gates.

Task plan: CGM Task Template → Sea Import Workflow (via task_engine)
Workflow states: CGM Sea Import Workflow (Project)
Task gates: CGM Shipping Settings → custom_sea_workflow_task_gates
"""
from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	PRE_CLEARANCE_STAGE,
	POST_CLEARANCE_STAGE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.inspection import (
	sea_import_task_sequence_no,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	SEA_IMPORT_TEMPLATE,
	sea_import_flow_keys,
	sql_task_flow_key_in,
	stored_task_flow_key,
	task_flow_key_in_filter,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import load_sea_task_template

AUTO_COMPLETE_INTAKE_REMARK = (
	"Auto-completed at Project creation: shipment documents were received and "
	"approved on Lead/Opportunity and are already on the Project file."
)


def get_tracking_workflow_states() -> list[str]:
	"""Ordered shipment workflow states for progress chart and gate sync."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_sea_import_workflow_states,
	)

	return get_sea_import_workflow_states()


def sea_task_count() -> int:
	"""Number of steps in the configured sea import task template."""
	return len(load_sea_task_template())


def is_sea_payment_task(task) -> bool:
	"""Finance payment step on sea import (delegates to CGM Shipping Settings)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_sea_finance_payment_task,
	)

	return is_sea_finance_payment_task(task)


def auto_complete_initial_sea_tasks(project: str) -> list[str]:
	"""Attach Project docs to auto-complete steps, then mark them Completed."""
	from frappe.utils import now_datetime

	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		carry_project_documents_to_sea_tasks,
	)

	carry_project_documents_to_sea_tasks(project)

	completed = []
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		auto_complete_sequences,
	)

	for seq in sorted(auto_complete_sequences()):
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			get_task_name_by_sequence,
		)

		task_name = get_task_name_by_sequence(project, seq)
		if not task_name:
			continue
		if frappe.db.get_value("Task", task_name, "status") == "Completed":
			completed.append(task_name)
			continue
		task = frappe.get_doc("Task", task_name)
		task.status = "Completed"
		task.completed_by = frappe.session.user
		task.completed_on = now_datetime()
		task.description = AUTO_COMPLETE_INTAKE_REMARK
		frappe.flags.cgm_auto_completing_sea_task = True
		try:
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.cgm_auto_completing_sea_task = False
		completed.append(task_name)
	return completed


def effective_completed_task_seqs(tasks: list) -> set[int]:
	"""Task sequences that count as done for workflow progress."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_permit_stage_for_sequence,
		is_permit_application_task,
	)

	completed: set[int] = set()
	for row in tasks:
		seq = int(row.get("custom_sequence_no") or 0)
		if not seq:
			continue
		if row.get("status") == "Completed":
			completed.add(seq)
		elif (
			is_permit_application_task(seq)
			and row.get("custom_permit_invoices_submitted")
		):
			# Permit application stays Open until finance completes - still unlocks finance step.
			completed.add(seq)
	return completed


def furthest_contiguous_completed_seq(completed_seqs: set[int]) -> int:
	"""Highest sequence reachable without gaps from seq 1.

	Prevents a later completed task (or drifted sequence) from unlocking
	workflow stages that earlier open tasks still block.
	"""
	seq = 0
	while (seq + 1) in completed_seqs:
		seq += 1
	return seq


def derive_workflow_progress_from_tasks(
	tasks: list,
	states: list[str] | None = None,
	gates: dict | None = None,
) -> tuple[str, int]:
	"""Furthest workflow state supported by completed clearance tasks (progress chart)."""
	states = states or get_tracking_workflow_states()
	if not states:
		return "Draft", 0
	completed_seqs = effective_completed_task_seqs(tasks)
	if not completed_seqs:
		return states[0], 0
	# Contiguous progress — not max(seq) — so the chart cannot jump past open tasks.
	progress_seq = furthest_contiguous_completed_seq(completed_seqs)
	progress_status = states[0]
	progress_index = 0
	if gates is None:
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			get_workflow_task_gates,
		)

		gates = get_workflow_task_gates()

	for state in states:
		gate_row = gates.get(state) if gates else None
		gate = gate_row.get("min_completed_task_seq") if gate_row else None
		if gate and progress_seq >= gate:
			progress_status = state
			progress_index = states.index(state)
	return progress_status, progress_index


def _sea_task_progress_fields() -> list[str]:
	"""Fields for workflow sync - only columns that exist on Task (safe before migrate)."""
	fields = ["custom_sequence_no", "status", "custom_permit_invoices_submitted"]
	meta = frappe.get_meta("Task")
	if meta.has_field("custom_ucr_invoice_submitted"):
		fields.append("custom_ucr_invoice_submitted")
	return fields


def _project_workflow_flow_keys(project: str) -> tuple[str, ...]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
		get_project_workflow_flow_keys,
	)

	keys = get_project_workflow_flow_keys(project)
	if keys:
		return keys
	return tuple(sea_import_flow_keys())


def sync_project_shipment_status_from_tasks(project: str) -> str | None:
	"""Align Project shipment status with completed clearance tasks (advance or rewind)."""
	if frappe.flags.get("cgm_skip_task_project_sync"):
		return None

	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
		get_clearance_workflow_gates_for_project,
		get_clearance_workflow_states_for_project,
		project_uses_clearance_workflow_states,
	)

	proj = frappe.get_doc("Project", project)
	if not project_uses_clearance_workflow_states(proj):
		return None

	tasks = frappe.get_all(
		"Task",
		filters={
			"project": project,
			"custom_task_flow_key": ["in", list(_project_workflow_flow_keys(project))],
		},
		fields=_sea_task_progress_fields(),
		limit=100,
	)
	states = get_clearance_workflow_states_for_project(proj)
	gates = get_clearance_workflow_gates_for_project(proj)
	progress_status, _ = derive_workflow_progress_from_tasks(tasks, states=states, gates=gates)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
		cap_workflow_status_for_intake,
	)

	progress_status = cap_workflow_status_for_intake(proj, progress_status, states)
	current = frappe.db.get_value("Project", project, "custom_shipment_status") or "Draft"
	if not states:
		return None
	if progress_status == current:
		return None
	if progress_status not in states:
		return None

	frappe.db.set_value(
		"Project",
		project,
		"custom_shipment_status",
		progress_status,
		update_modified=False,
	)
	if frappe.get_meta("Project").has_field("workflow_state"):
		frappe.db.set_value(
			"Project",
			project,
			"workflow_state",
			progress_status,
			update_modified=False,
		)
	frappe.clear_document_cache("Project", project)
	frappe.publish_realtime(
		"cgm_project_tracking_refresh",
		{"project": project},
		doctype="Project",
		docname=project,
	)
	return progress_status


def get_incomplete_sea_tasks(project: str, before_sequence: int) -> list[dict]:
	"""Tasks with sequence < before_sequence that are not Completed/Cancelled.

	Used for Project status / closure gates (chart progress), not for everyday
	task completion — non-finance steps may finish out of order.
	"""
	if before_sequence <= 1:
		return []
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_permit_stage_for_sequence,
		is_entry_application_task,
		is_kpa_application_task,
		is_permit_application_task,
		is_shipping_line_application_task,
		is_ucr_application_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		permit_invoices_ready,
		ucr_invoice_ready,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		invoice_submitted as application_invoice_submitted,
	)

	flow_in = sql_task_flow_key_in(SEA_IMPORT_TEMPLATE, column="custom_task_flow_key")
	rows = frappe.db.sql(
		f"""
		SELECT name, subject, custom_sequence_no AS seq, status
		FROM `tabTask`
		WHERE project = %s
		  AND {flow_in}
		  AND custom_sequence_no < %s
		  AND status NOT IN ('Completed', 'Cancelled')
		ORDER BY custom_sequence_no ASC
		LIMIT 10
		""",
		(project, before_sequence),
		as_dict=True,
	)
	# UCR / pre-clearance permit application tasks stay Open while Finance pays; invoice submitted unlocks finance.
	filtered = [
		r
		for r in rows
		if not (
			is_permit_application_task(r.seq)
			and get_permit_stage_for_sequence(r.seq) == PRE_CLEARANCE_STAGE
			and permit_invoices_ready(r.name)
		)
		and not (is_ucr_application_task(r.seq) and ucr_invoice_ready(r.name))
		and not (
			is_entry_application_task(r.seq)
			and application_invoice_submitted(
				r.name, APPLICATION_FINANCE_PROFILES["Entry Application"]
			)
		)
		and not (
			is_shipping_line_application_task(r.seq)
			and application_invoice_submitted(
				r.name, APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
			)
		)
		and not (
			is_kpa_application_task(r.seq)
			and application_invoice_submitted(
				r.name, APPLICATION_FINANCE_PROFILES["KPA Application"]
			)
		)
	]
	# Transport tasks (21–26) run in parallel — do not block each other.
	if 21 <= before_sequence <= 26:
		filtered = [
			r for r in filtered if not (21 <= r.seq < before_sequence)
		]
	return filtered


def _application_invoice_ready_for_finance(app_name: str, app_seq: int) -> bool:
	"""True when the paired application has submitted its invoice (finance may proceed)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		invoice_submitted as application_invoice_submitted,
		profile_by_requirement_type,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_entry_application_task,
		is_kpa_application_task,
		is_permit_application_task,
		is_shipping_line_application_task,
		is_ucr_application_task,
		rows_by_sequence,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		permit_invoices_ready,
		ucr_invoice_ready,
	)

	if is_ucr_application_task(app_seq) and ucr_invoice_ready(app_name):
		return True
	if is_permit_application_task(app_seq) and permit_invoices_ready(app_name):
		return True
	if is_entry_application_task(app_seq) and application_invoice_submitted(
		app_name, APPLICATION_FINANCE_PROFILES["Entry Application"]
	):
		return True
	if is_shipping_line_application_task(app_seq) and application_invoice_submitted(
		app_name, APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
	):
		return True
	if is_kpa_application_task(app_seq) and application_invoice_submitted(
		app_name, APPLICATION_FINANCE_PROFILES["KPA Application"]
	):
		return True
	for row in rows_by_sequence().get(app_seq, []):
		profile = profile_by_requirement_type(row.requirement_type)
		if profile and application_invoice_submitted(app_name, profile):
			return True
	return False


def get_incomplete_finance_pair_blockers(project: str, finance_sequence: int) -> list[dict]:
	"""For finance payment steps only: block if the paired application is not ready.

	Non-finance sequences return [] so inspection / Lodge DO / field clearance can
	complete without waiting on earlier chart steps.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		application_sequence_for_finance_sequence,
		is_finance_payment_task,
	)

	if not project or not is_finance_payment_task(finance_sequence):
		return []
	app_seq = application_sequence_for_finance_sequence(finance_sequence)
	if not app_seq:
		return []

	flow_in = sql_task_flow_key_in(SEA_IMPORT_TEMPLATE, column="custom_task_flow_key")
	rows = frappe.db.sql(
		f"""
		SELECT name, subject, custom_sequence_no AS seq, status
		FROM `tabTask`
		WHERE project = %s
		  AND {flow_in}
		  AND custom_sequence_no = %s
		LIMIT 1
		""",
		(project, app_seq),
		as_dict=True,
	)
	if not rows:
		return []
	app = rows[0]
	if app.status in ("Completed", "Cancelled"):
		return []
	if _application_invoice_ready_for_finance(app.name, app.seq):
		return []
	return [app]


def get_all_sea_tasks_for_project(project: str, user: str | None = None) -> list[dict]:
	"""All sea clearance tasks on a project visible to the user (incl. Completed)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		filter_sea_tasks_for_user,
	)

	if not project:
		return []
	flow_in = sql_task_flow_key_in(SEA_IMPORT_TEMPLATE, column="custom_task_flow_key")
	rows = frappe.db.sql(
		f"""
		SELECT name, subject, custom_sequence_no AS seq, status, department, owner, _assign
		FROM `tabTask`
		WHERE project = %s
		  AND {flow_in}
		ORDER BY custom_sequence_no ASC
		""",
		(project,),
		as_dict=True,
	)
	return filter_sea_tasks_for_user(rows, user=user)


def get_open_sea_tasks(project: str, user: str | None = None) -> list[dict]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		filter_sea_tasks_for_user,
	)

	flow_in = sql_task_flow_key_in(SEA_IMPORT_TEMPLATE, column="custom_task_flow_key")
	rows = frappe.db.sql(
		f"""
		SELECT name, subject, custom_sequence_no AS seq, status, department, owner, _assign
		FROM `tabTask`
		WHERE project = %s
		  AND {flow_in}
		  AND status NOT IN ('Completed', 'Cancelled')
		ORDER BY custom_sequence_no ASC
		""",
		(project,),
		as_dict=True,
	)
	return filter_sea_tasks_for_user(rows, user=user)


def enforce_sea_tasks_exist(project: str) -> None:
	if not frappe.db.exists(
		"Task",
		{"project": project, "custom_task_flow_key": task_flow_key_in_filter()},
	):
		total = sea_task_count()
		frappe.throw(
			"Generate the <b>Sea Task Plan</b> on this Project first "
			f"({total} ordered steps)."
		)


def enforce_workflow_task_gate(project: str, new_status: str) -> None:
	"""Block workflow advance until prior sea tasks in the chart are Completed."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import get_gate_for_state

	gate_row = get_gate_for_state(new_status)
	if not gate_row:
		return

	required_seq = int(gate_row.get("min_completed_task_seq") or 0)
	gate_rule = gate_row.get("gate_rule") or "Standard"
	if not required_seq:
		return

	enforce_sea_tasks_exist(project)

	if gate_rule == "Permit Invoices Submitted":
		from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
			get_permit_stage_for_sequence,
			is_permit_application_task,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			permit_invoices_ready_for_project,
		)

		stage = (
			get_permit_stage_for_sequence(required_seq)
			if is_permit_application_task(required_seq)
			else PRE_CLEARANCE_STAGE
		)
		if not permit_invoices_ready_for_project(project, stage):
			frappe.throw(
				f"Attach all permit invoices on the <b>{stage}</b> permit application task and save — "
				"Finance is notified automatically — before advancing workflow."
			)
		return

	if gate_rule == "UCR Finance Complete":
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			get_ucr_finance_task,
			ucr_finance_ready_to_complete,
		)

		finance_task_name = get_ucr_finance_task(project)
		if not finance_task_name:
			frappe.throw("Generate the sea task plan and complete <b>Finance pays UCR</b> first.")
		finance_task = frappe.get_doc("Task", finance_task_name)
		if finance_task.status != "Completed" or not ucr_finance_ready_to_complete(finance_task):
			frappe.throw(
				"Cannot move to <b>UCR Paid</b> until <b>Finance pays UCR</b> is completed: "
				"UCR invoice verified and UCR receipt verified by Finance."
			)
		return

	if gate_rule == "Entry Finance Complete":
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			enforce_entry_finance_gate,
		)

		enforce_entry_finance_gate(project)
		return

	if gate_rule == "KPA Finance Complete":
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_application_finance import (
			enforce_kpa_finance_gate,
		)

		enforce_kpa_finance_gate(project)
		return

	if gate_rule == "All Sea Tasks Complete":
		enforce_all_sea_tasks_complete(project)
		return

	incomplete = get_incomplete_sea_tasks(project, required_seq + 1)
	if incomplete:
		lines = [
			f"Task {r.seq}: {r.subject} ({r.status or 'Open'})" for r in incomplete[:5]
		]
		frappe.throw(
			f"Cannot move to <b>{new_status}</b> until prior sea tasks are <b>Completed</b> "
			f"(steps 1–{required_seq} in the Sea Freight Clearance chart).<br><br>"
			+ "<br>".join(lines)
		)


def get_sea_closure_blockers(project: str) -> list[str]:
	"""Return human-readable blockers when the sea chart is not fully complete."""
	blockers: list[str] = []
	flow_filter = task_flow_key_in_filter()
	if not frappe.db.exists(
		"Task", {"project": project, "custom_task_flow_key": flow_filter}
	):
		return ["Sea Task Plan not generated on this Project"]
	total = sea_task_count()
	created = frappe.db.count(
		"Task", {"project": project, "custom_task_flow_key": flow_filter}
	)
	if created < total:
		blockers.append(
			f"Sea task plan has {created} tasks; the clearance chart requires {total}. "
			"Regenerate the Sea Task Plan (reset) for this project."
		)
	incomplete = get_incomplete_sea_tasks(project, total + 1)
	if incomplete:
		lines = [f"Task {r.seq}: {r.subject} ({r.status or 'Open'})" for r in incomplete[:8]]
		blockers.append(
			f"Sea clearance tasks not all Completed ({len(incomplete)} open): " + "; ".join(lines)
		)
	return blockers


def enforce_all_sea_tasks_complete(project: str) -> None:
	"""FINAL RULE: all sea clearance tasks must be Completed in order."""
	blockers = get_sea_closure_blockers(project)
	if blockers:
		frappe.throw("<br>".join(blockers))


# ─── Sea Task Template & Plan (moved from utils.py) ───────────────────────────
def mark_task_completed(task) -> None:
	"""Persist Completed and keep the in-memory doc aligned (see workflow.mark_task_completed)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		mark_task_completed as _mark,
	)

	_mark(task)


@frappe.whitelist()
def backfill_intake_documents_on_sea_tasks(project):
	"""Copy Project shipment documents onto tasks 1–2 (for projects created before this feature)."""
	frappe.has_permission("Project", ptype="write", throw=True)
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		carry_project_documents_to_sea_tasks,
	)

	carried = carry_project_documents_to_sea_tasks(project)
	auto_complete_initial_sea_tasks(project)
	return {"tasks_updated": carried}


def bootstrap_sea_task_plan_for_project(project_name: str) -> dict | None:
	"""
	For Sea projects with CRM-approved CI/PKL: create the 24-task plan and auto-complete tasks 1–2.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
		project_ready_for_documents_received,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
		sea_import_enabled_for_project,
	)

	project_doc = frappe.get_doc("Project", project_name)

	if not sea_import_enabled_for_project(project_doc):
		return None
	if not project_ready_for_documents_received(project_doc):
		return None

	if frappe.db.exists(
		"Task",
		{"project": project_name, "custom_task_flow_key": task_flow_key_in_filter()},
	):
		done = auto_complete_initial_sea_tasks(project_name)
		return {"auto_completed": done, "created": 0}

	result = create_sea_import_task_plan_internal(project_name)
	result["auto_completed"] = auto_complete_initial_sea_tasks(project_name)
	return result


def create_sea_import_task_plan_internal(project, reset=False):
	"""Generate ordered sea-import tasks (internal; no duplicate check unless reset)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
		project_ready_for_documents_received,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
		sea_import_enabled_for_project,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		ensure_sea_task_requirements_configured,
	)

	ensure_sea_task_requirements_configured()

	project_doc = frappe.get_doc("Project", project)

	if not sea_import_enabled_for_project(project_doc):
		frappe.throw("This task plan is for sea-import shipment types only.")

	flow_filter = task_flow_key_in_filter()
	existing = frappe.get_all(
		"Task",
		filters={"project": project, "custom_task_flow_key": flow_filter},
		fields=["name"],
		limit=1,
	)
	if existing and not frappe.utils.cint(reset):
		frappe.throw("Sea task plan already exists. Use reset=1 if you want to regenerate it.")
	if existing and frappe.utils.cint(reset):
		for d in frappe.get_all(
			"Task",
			filters={"project": project, "custom_task_flow_key": flow_filter},
			fields=["name"],
		):
			frappe.delete_doc("Task", d.name, ignore_permissions=True, force=True)

	task_template = load_sea_task_template()
	created = []
	created_by_seq: dict[int, str] = {}
	canonical_flow_key = stored_task_flow_key(SEA_IMPORT_TEMPLATE)

	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		resolve_department_name,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		sea_finance_dependency_pairs,
	)

	finance_depends_on_app = {fin: app for app, fin in sea_finance_dependency_pairs()}

	frappe.flags.cgm_skip_task_project_sync = True
	try:
		for idx, item in enumerate(task_template, start=1):
			subject = item.get("subject")
			if not subject:
				frappe.throw(f"Task template item at position {idx} has no subject.")

			seq = sea_import_task_sequence_no(idx)
			task = frappe.new_doc("Task")
			task.subject = subject
			task.project = project
			task.custom_task_flow_key = canonical_flow_key
			task.custom_sequence_no = seq
			task.department = resolve_department_name(item.get("department"), company=project_doc.company)
			task.status = "Open"

			# Only link finance payment tasks to their application counterpart.
			app_seq = finance_depends_on_app.get(seq)
			if app_seq and app_seq in created_by_seq:
				task.append("depends_on", {"task": created_by_seq[app_seq]})

			task.insert(ignore_permissions=True)
			if task.owner != "Administrator" and frappe.db.exists("User", "Administrator"):
				frappe.db.set_value(
					"Task", task.name, "owner", "Administrator", update_modified=False
				)
				task.owner = "Administrator"

			created_by_seq[seq] = task.name
			created.append(task.name)
	finally:
		frappe.flags.cgm_skip_task_project_sync = False

	out = {"created": created, "count": len(created)}
	if project_ready_for_documents_received(project_doc):
		frappe.flags.cgm_skip_task_project_sync = True
		try:
			out["auto_completed"] = auto_complete_initial_sea_tasks(project)
		finally:
			frappe.flags.cgm_skip_task_project_sync = False
	return out


@frappe.whitelist()
def create_sea_import_task_plan(project, reset=False):
	"""Generate sea-import tasks; only application↔finance pairs get depends_on links."""
	frappe.has_permission("Task", ptype="create", throw=True)
	return create_sea_import_task_plan_internal(project, reset=reset)
