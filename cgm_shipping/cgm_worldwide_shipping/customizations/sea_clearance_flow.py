"""
Sea Freight Clearance - ordered task plan and workflow gates.

Task plan rows: CGM Shipping Settings → custom_sea_import_task_template
Workflow states: CGM Sea Import Workflow (Project)
Task gates: CGM Shipping Settings → custom_sea_workflow_task_gates
"""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY
from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
	PRE_CLEARANCE_STAGE,
	get_permit_stage_for_sequence,
	is_permit_application_task,
	is_ucr_application_task,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_gates import (
	get_sea_import_workflow_states,
)

AUTO_COMPLETE_INTAKE_REMARK = (
	"Auto-completed at Project creation: shipment documents were received and "
	"approved on Lead/Opportunity and are already on the Project file."
)


def get_tracking_workflow_states() -> list[str]:
	"""Ordered shipment workflow states for progress chart and gate sync."""
	return get_sea_import_workflow_states()


def sea_task_count() -> int:
	"""Number of steps in the configured sea import task template."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import load_sea_task_template

	return len(load_sea_task_template())


def is_sea_payment_task(task) -> bool:
	"""Finance payment step on sea import (delegates to CGM Shipping Settings)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
		is_sea_finance_payment_task,
	)

	return is_sea_finance_payment_task(task)


def is_sea_auto_completed_task(task) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
		is_sea_auto_complete_task,
	)

	return is_sea_auto_complete_task(task)


def is_sea_clearance_task(task) -> bool:
	return task.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY


def task_should_show_documents(seq: int) -> bool:
	"""Task Documents table - not for CRM intake steps auto-done at project create."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
		is_auto_complete_task,
	)

	return not is_auto_complete_task(seq)


def task_should_show_payment_fields(seq: int) -> bool:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
		is_finance_payment_task,
	)

	return is_finance_payment_task(seq)


def auto_complete_initial_sea_tasks(project: str) -> list[str]:
	"""Attach Project docs to auto-complete steps, then mark them Completed."""
	from frappe.utils import now_datetime

	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		carry_project_shipment_documents_to_sea_tasks,
	)

	carry_project_shipment_documents_to_sea_tasks(project)

	completed = []
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_requirements_service import (
		auto_complete_sequences,
	)

	for seq in sorted(auto_complete_sequences()):
		task_name = frappe.db.get_value(
			"Task",
			{
				"project": project,
				"custom_task_flow_key": SEA_TASK_FLOW_KEY,
				"custom_sequence_no": seq,
			},
			"name",
		)
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
	completed: set[int] = set()
	for row in tasks:
		seq = int(row.get("custom_sequence_no") or 0)
		if not seq:
			continue
		if row.get("status") == "Completed":
			completed.add(seq)
		elif (
			is_permit_application_task(seq)
			and get_permit_stage_for_sequence(seq) == PRE_CLEARANCE_STAGE
			and row.get("custom_permit_invoices_submitted")
		):
			# Pre-clearance permit application stays Open until finance completes - still unlocks finance step.
			completed.add(seq)
	return completed


def derive_workflow_progress_from_tasks(
	tasks: list,
	states: list[str] | None = None,
) -> tuple[str, int]:
	"""Furthest workflow state supported by completed sea tasks (for the progress chart)."""
	states = states or get_tracking_workflow_states()
	if not states:
		return "Draft", 0
	completed_seqs = effective_completed_task_seqs(tasks)
	if not completed_seqs:
		return states[0], 0
	max_seq = max(completed_seqs)
	progress_status = states[0]
	progress_index = 0
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_gates import (
		get_workflow_task_gates,
	)

	for state in states:
		gate_row = get_workflow_task_gates().get(state)
		gate = gate_row.get("min_completed_task_seq") if gate_row else None
		if gate and max_seq >= gate:
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


def sync_project_shipment_status_from_tasks(project: str) -> str | None:
	"""Advance Project workflow field when sea tasks have passed the current state."""
	if frappe.db.get_value("Project", project, "custom_mode_of_transport") != "Sea":
		return None
	tasks = frappe.get_all(
		"Task",
		filters={"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY},
		fields=_sea_task_progress_fields(),
		limit=30,
	)
	progress_status, _ = derive_workflow_progress_from_tasks(tasks)
	current = frappe.db.get_value("Project", project, "custom_shipment_status") or "Draft"
	states = get_tracking_workflow_states()
	if not states:
		return None
	try:
		if states.index(progress_status) <= states.index(current):
			return None
	except ValueError:
		return None
	frappe.db.set_value(
		"Project",
		project,
		"custom_shipment_status",
		progress_status,
		update_modified=False,
	)
	frappe.publish_realtime(
		"cgm_project_tracking_refresh",
		{"project": project},
		doctype="Project",
		docname=project,
	)
	return progress_status


def get_incomplete_sea_tasks(project: str, before_sequence: int) -> list[dict]:
	"""Tasks with sequence < before_sequence that are not Completed/Cancelled."""
	if before_sequence <= 1:
		return []
	from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
		permit_invoices_ready,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
		ucr_invoice_ready,
	)

	rows = frappe.db.sql(
		"""
		SELECT name, subject, custom_sequence_no AS seq, status
		FROM `tabTask`
		WHERE project = %s
		  AND custom_task_flow_key = %s
		  AND custom_sequence_no < %s
		  AND status NOT IN ('Completed', 'Cancelled')
		ORDER BY custom_sequence_no ASC
		LIMIT 10
		""",
		(project, SEA_TASK_FLOW_KEY, before_sequence),
		as_dict=True,
	)
	# UCR / pre-clearance permit application tasks stay Open while Finance pays; invoice submitted unlocks finance.
	return [
		r
		for r in rows
		if not (
			is_permit_application_task(r.seq)
			and get_permit_stage_for_sequence(r.seq) == PRE_CLEARANCE_STAGE
			and permit_invoices_ready(r.name)
		)
		and not (is_ucr_application_task(r.seq) and ucr_invoice_ready(r.name))
	]


def get_all_sea_tasks_for_project(project: str, user: str | None = None) -> list[dict]:
	"""All sea clearance tasks on a project visible to the user (incl. Completed)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_permissions import (
		filter_sea_tasks_for_user,
	)

	if not project:
		return []
	rows = frappe.db.sql(
		"""
		SELECT name, subject, custom_sequence_no AS seq, status, department, owner, _assign
		FROM `tabTask`
		WHERE project = %s
		  AND custom_task_flow_key = %s
		ORDER BY custom_sequence_no ASC
		""",
		(project, SEA_TASK_FLOW_KEY),
		as_dict=True,
	)
	return filter_sea_tasks_for_user(rows, user=user)


def get_open_sea_tasks(project: str, user: str | None = None) -> list[dict]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_permissions import (
		filter_sea_tasks_for_user,
	)

	rows = frappe.db.sql(
		"""
		SELECT name, subject, custom_sequence_no AS seq, status, department, owner, _assign
		FROM `tabTask`
		WHERE project = %s
		  AND custom_task_flow_key = %s
		  AND status NOT IN ('Completed', 'Cancelled')
		ORDER BY custom_sequence_no ASC
		""",
		(project, SEA_TASK_FLOW_KEY),
		as_dict=True,
	)
	return filter_sea_tasks_for_user(rows, user=user)


def enforce_sea_tasks_exist(project: str) -> None:
	if not frappe.db.exists(
		"Task",
		{"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY},
	):
		total = sea_task_count()
		frappe.throw(
			"Generate the <b>Sea Task Plan</b> on this Project first "
			f"({total} ordered steps)."
		)


def enforce_workflow_task_gate(project: str, new_status: str) -> None:
	"""Block workflow advance until prior sea tasks in the chart are Completed."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_gates import get_gate_for_state

	gate_row = get_gate_for_state(new_status)
	if not gate_row:
		return

	required_seq = int(gate_row.get("min_completed_task_seq") or 0)
	gate_rule = gate_row.get("gate_rule") or "Standard"
	if not required_seq:
		return

	enforce_sea_tasks_exist(project)

	if gate_rule == "Permit Invoices Submitted":
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			permit_invoices_ready_for_project,
		)

		if not permit_invoices_ready_for_project(project, "Pre-clearance"):
			frappe.throw(
				"Submit all permit invoices to Finance on <b>Apply for Pre-Clearance Permits</b> "
				"using <b>Notify Finance - invoices ready</b> before advancing workflow."
			)
		return

	if gate_rule == "UCR Finance Complete":
		from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
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
	if not frappe.db.exists(
		"Task", {"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY}
	):
		return ["Sea Task Plan not generated on this Project"]
	total = sea_task_count()
	created = frappe.db.count(
		"Task", {"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY}
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
