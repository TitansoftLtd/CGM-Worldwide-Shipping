"""
Sea Freight Clearance - ordered task plan and workflow gates.

Task plan: CGM Task Template → Sea Import Workflow (via task_engine)
Workflow states: CGM Sea Import Workflow (Project)
Task gates: CGM Task Template → Sea Import Workflow → Shipment Status Gates
"""
from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	PRE_CLEARANCE_STAGE,
	POST_CLEARANCE_STAGE,
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
	"""Attach Project docs to the intake tasks, then mark them Completed.

	The intake tasks are the project template's rows marked Complete When Client
	Documents Are In. Sea Import's step numbers would pick other tasks on another
	template - that is how Sea Transit's step 2 got completed.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		carry_project_documents_to_sea_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
		get_workflow_template_name,
	)
	from cgm_shipping.cgm_worldwide_shipping.task_engine import (
		_auto_complete_intake_tasks,
		intake_sequences,
	)

	template = get_workflow_template_name(project)
	seqs = intake_sequences(template) if template else []
	if not seqs:
		return []
	carry_project_documents_to_sea_tasks(project, task_sequences=seqs)
	return _auto_complete_intake_tasks(project, template, sequences=seqs)


def effective_completed_task_seqs(tasks: list) -> set[int]:
	"""Task sequences that count as done for workflow progress.

	A permit application with its invoices submitted counts as done - it stays
	Open until Finance completes. Its Task Role says which rows those are.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		ROLE_PERMIT_APPLICATION,
	)

	completed: set[int] = set()
	for row in tasks:
		seq = int(row.get("custom_sequence_no") or 0)
		if not seq:
			continue
		if row.get("status") == "Completed":
			completed.add(seq)
		elif row.get("custom_permit_invoices_submitted") and (
			(row.get("custom_task_role") or "").strip() == ROLE_PERMIT_APPLICATION
		):
			completed.add(seq)
	return completed


def all_clearance_tasks_completed(tasks: list, gates: dict | None = None) -> bool:
	"""True when every workflow task on the project is done (nothing left open)."""
	if not tasks:
		return False
	if any(t.get("status") not in ("Completed", "Cancelled") for t in tasks):
		return False
	completed_seqs = effective_completed_task_seqs(tasks)
	if not completed_seqs:
		return False
	gates = _resolve_workflow_gates(gates)
	task_seqs = {
		int(t.get("custom_sequence_no") or 0)
		for t in tasks
		if int(t.get("custom_sequence_no") or 0)
	}
	if not task_seqs or not task_seqs.issubset(completed_seqs):
		return False
	last_gate_seq = max(
		(row.get("min_completed_task_seq") or 0 for row in gates.values()),
		default=0,
	)
	# Full plan must exist before Completed — partial plans stay on the furthest gate.
	if last_gate_seq and max(task_seqs) < last_gate_seq:
		return False
	return True


def _resolve_workflow_gates(gates: dict | None) -> dict:
	if gates is not None:
		return gates
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		get_workflow_task_gates,
	)

	return get_workflow_task_gates()


def derive_workflow_passed_states(
	tasks: list,
	states: list[str] | None = None,
	gates: dict | None = None,
) -> set[str]:
	"""Workflow states whose task gate is satisfied (supports out-of-order completion)."""
	states = states or get_tracking_workflow_states()
	if not states:
		return set()
	gates = _resolve_workflow_gates(gates)
	completed_seqs = effective_completed_task_seqs(tasks)
	passed: set[str] = set()
	for state in states:
		if state == "Completed":
			continue
		gate_row = gates.get(state) if gates else None
		gate_seq = gate_row.get("min_completed_task_seq") if gate_row else None
		if gate_seq and gate_seq in completed_seqs:
			passed.add(state)
	# Draft has no task gate - pass it together with Documents Received (the intake step).
	if "Draft" in states and "Documents Received" in passed:
		passed.add("Draft")
	if all_clearance_tasks_completed(tasks, gates=gates) and "Completed" in states:
		passed.add("Completed")
	return passed


def derive_workflow_progress_from_tasks(
	tasks: list,
	states: list[str] | None = None,
	gates: dict | None = None,
) -> tuple[str, int]:
	"""Furthest workflow state reached from completed clearance tasks (progress chart).

	Each workflow pill maps to a task sequence gate. A state counts as reached when
	that specific task is done — work may finish out of order (e.g. Shipping Line
	before UCR). When every clearance task is Completed, status is Completed.
	"""
	states = states or get_tracking_workflow_states()
	if not states:
		return "Draft", 0
	completed_seqs = effective_completed_task_seqs(tasks)
	if not completed_seqs and not all_clearance_tasks_completed(tasks, gates=gates):
		return states[0], 0

	gates = _resolve_workflow_gates(gates)
	passed = derive_workflow_passed_states(tasks, states=states, gates=gates)

	if all_clearance_tasks_completed(tasks, gates=gates) and "Completed" in states:
		idx = states.index("Completed")
		return "Completed", idx

	progress_status = states[0]
	progress_index = 0
	all_done = all_clearance_tasks_completed(tasks, gates=gates)
	for i, state in enumerate(states):
		if state == "Completed" and not all_done:
			continue
		if state in passed:
			progress_status = state
			progress_index = i
	return progress_status, progress_index


def _sea_task_progress_fields() -> list[str]:
	"""Fields for workflow sync - only columns that exist on Task (safe before migrate)."""
	fields = ["custom_sequence_no", "status", "custom_permit_invoices_submitted"]
	meta = frappe.get_meta("Task")
	if meta.has_field("custom_ucr_invoice_submitted"):
		fields.append("custom_ucr_invoice_submitted")
	if meta.has_field("custom_task_role"):
		# effective_completed_task_seqs tells permit applications by their role.
		fields.append("custom_task_role")
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


def get_incomplete_sea_tasks(
	project: str, before_sequence: int, *, parallel_transport: bool = True
) -> list[dict]:
	"""Tasks with sequence < before_sequence that are not Completed/Cancelled.

	Used for Project status / closure gates (chart progress), not for everyday
	task completion — non-finance steps may finish out of order. With
	``parallel_transport``, a gate on a transport task is not held up by earlier
	transport tasks - they run in parallel - but its own task still counts.
	Transport is told by the task's Container Step, not its step number.
	"""
	if before_sequence <= 1:
		return []
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
		invoice_submitted as application_invoice_submitted,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		PAYMENT_KIND_TO_PROFILE_KEY,
		ROLE_APPLICATION,
		ROLE_PERMIT_APPLICATION,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		permit_invoices_ready,
		ucr_invoice_ready,
	)

	flow_in = sql_task_flow_key_in(SEA_IMPORT_TEMPLATE, column="custom_task_flow_key")
	rows = frappe.db.sql(
		f"""
		SELECT name, subject, custom_sequence_no AS seq, status,
			custom_container_step AS container_step,
			custom_task_role AS role, custom_payment_kind AS kind, custom_permit_stage AS stage
		FROM `tabTask`
		WHERE project = %s
		  AND {flow_in}
		  AND custom_sequence_no < %s
		  AND status NOT IN ('Completed', 'Cancelled')
		ORDER BY custom_sequence_no ASC
		""",
		(project, before_sequence),
		as_dict=True,
	)

	def handed_to_finance(row) -> bool:
		"""Applications stay Open while Finance pays: once the invoice is with Finance
		(pre-clearance permits: every permit invoice) they no longer hold up the chart."""
		if row.role == ROLE_PERMIT_APPLICATION:
			return row.stage == PRE_CLEARANCE_STAGE and permit_invoices_ready(row.name)
		if row.role != ROLE_APPLICATION:
			return False
		key = PAYMENT_KIND_TO_PROFILE_KEY.get(row.kind or "")
		if key == "UCR Application":
			return ucr_invoice_ready(row.name)
		return bool(key) and application_invoice_submitted(row.name, APPLICATION_FINANCE_PROFILES[key])

	filtered = [r for r in rows if not handed_to_finance(r)]
	if parallel_transport:
		gate_seq = before_sequence - 1
		filtered = _without_parallel_transport(
			filtered, gate_seq, _gate_task_is_transport(project, gate_seq)
		)
	return filtered


def _gate_task_is_transport(project: str, gate_seq: int) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		TRANSPORT_CONTAINER_STEPS,
	)

	step = frappe.db.get_value(
		"Task",
		{
			"project": project,
			"custom_task_flow_key": ["in", list(sea_import_flow_keys())],
			"custom_sequence_no": gate_seq,
		},
		"custom_container_step",
	)
	return step in TRANSPORT_CONTAINER_STEPS


def _without_parallel_transport(rows: list, gate_seq: int, gate_is_transport: bool) -> list:
	"""Drop open transport tasks before a transport gate's own task - they run in parallel."""
	if not gate_is_transport:
		return rows
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		TRANSPORT_CONTAINER_STEPS,
	)

	return [
		r
		for r in rows
		if not (r.get("container_step") in TRANSPORT_CONTAINER_STEPS and r.get("seq") < gate_seq)
	]


def application_ready_for_finance(app_name: str) -> bool:
	"""True when a finance step's parent application has handed Finance its invoice.

	Read from the application's stamps, so it holds on every template.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		invoice_submitted as application_invoice_submitted,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		PAYMENT_KIND_TO_PROFILE_KEY,
		get_task_behaviour,
		profile_for_payment_kind,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
		permit_application_invoices_ready_for_finance,
		ucr_invoice_ready,
	)

	behaviour = get_task_behaviour(frappe.get_doc("Task", app_name))
	if behaviour.is_permit_application:
		return bool(permit_application_invoices_ready_for_finance(app_name))
	if not behaviour.is_application:
		return False
	if PAYMENT_KIND_TO_PROFILE_KEY.get(behaviour.payment_kind) == "UCR Application" and ucr_invoice_ready(
		app_name
	):
		return True
	profile = profile_for_payment_kind(behaviour.payment_kind)
	return bool(profile and application_invoice_submitted(app_name, profile))


def get_incomplete_finance_pair_blockers(finance_task) -> list[dict]:
	"""Sea Import finance steps: block while the paired application is not ready.

	The pair comes from the Task Role stamps. Other steps return [] so Lodge DO,
	field clearance and the like complete without waiting on earlier chart steps;
	other templates are held by their Depends On links (CGMTask.validate_status).
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		get_application_task,
		profile_for_task,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		get_permit_application_for_behaviour,
		get_task_behaviour,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		is_sea_import_task,
	)

	if not finance_task.get("project") or not is_sea_import_task(finance_task):
		return []
	behaviour = get_task_behaviour(finance_task)
	if behaviour.is_permit_finance:
		app_name = get_permit_application_for_behaviour(finance_task)
	elif behaviour.is_finance_payment:
		profile = profile_for_task(finance_task)
		app_name = get_application_task(finance_task.project, profile) if profile else None
	else:
		return []
	if not app_name or app_name == finance_task.name:
		return []
	rows = frappe.get_all(
		"Task",
		filters={"name": app_name},
		fields=["name", "subject", "custom_sequence_no as seq", "status"],
		limit=1,
	)
	if not rows or rows[0].status in ("Completed", "Cancelled"):
		return []
	if application_ready_for_finance(app_name):
		return []
	return rows


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
		SELECT name, subject, custom_sequence_no AS seq, status, department, owner, _assign,
			custom_task_role, custom_payment_kind, custom_permit_stage
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
		SELECT name, subject, custom_sequence_no AS seq, status, department, owner, _assign,
			custom_task_role, custom_payment_kind, custom_permit_stage
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
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
			ROLE_PERMIT_APPLICATION,
		)
		from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
			permit_invoices_ready_for_project,
		)

		# The gate's own task is the permit application whose invoices it waits on.
		stage = (
			frappe.db.get_value(
				"Task",
				{
					"project": project,
					"custom_task_flow_key": ["in", list(sea_import_flow_keys())],
					"custom_sequence_no": required_seq,
					"custom_task_role": ROLE_PERMIT_APPLICATION,
				},
				"custom_permit_stage",
			)
			or PRE_CLEARANCE_STAGE
		)
		if not permit_invoices_ready_for_project(project, stage):
			frappe.throw(
				f"Attach all permit invoices on the <b>{stage}</b> permit application task and save - "
				"Finance is notified automatically - before advancing workflow."
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
	# Every task up to the last step, transport included. The row count is not the
	# last step: removed steps leave gaps (Sea Import ends at 25 with 23 rows).
	last_step = max(
		(int(row.get("sequence_no") or 0) for row in load_sea_task_template()), default=total
	)
	incomplete = get_incomplete_sea_tasks(project, last_step + 1, parallel_transport=False)
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
	"""Copy Project shipment documents onto the intake tasks and complete them.

	For projects created before intake carry existed. The intake tasks come from
	the project's template (see auto_complete_initial_sea_tasks).
	"""
	frappe.has_permission("Project", ptype="write", throw=True)
	return {"tasks_updated": auto_complete_initial_sea_tasks(project)}



@frappe.whitelist()
def create_sea_import_task_plan(project, reset=False):
	"""Create the workflow task plan for a project.

	Delegates to task_engine, which is the single builder. The former local
	implementation rebuilt the plan from template row order and stamped only
	flow key and sequence number - tasks it produced carried no task_role or
	required document types, so role behaviour and document gating silently did
	not apply to them.
	"""
	frappe.has_permission("Task", ptype="create", throw=True)

	from cgm_shipping.cgm_worldwide_shipping.task_engine import create_project_tasks

	if frappe.utils.cint(reset):
		flow_filter = task_flow_key_in_filter()
		for row in frappe.get_all(
			"Task", filters={"project": project, "custom_task_flow_key": flow_filter}, pluck="name"
		):
			frappe.delete_doc("Task", row, ignore_permissions=True, force=True)

	return {"created": create_project_tasks(project)}
