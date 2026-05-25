"""
Sea Freight Clearance — ordered task plan and workflow gates.

Matches CGM Worldwide Shipping sea clearance chart (START → END).
"""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import SEA_TASK_FLOW_KEY

# Ordered sea import tasks (sequence = row order).
SEA_FREIGHT_TASK_TEMPLATE: list[dict[str, str]] = [
	{"task_subject": "Receive shipment documents from Client", "department": "Operations"},
	{"task_subject": "Share documents with Declarants", "department": "Operations"},
	{"task_subject": "Create UCR (IDF)", "department": "Declaration"},
	{"task_subject": "Finance pays UCR", "department": "Finance"},
	{
		"task_subject": "Apply for Pre-Clearance Permits (DVS, NBA, VMD, ACA)",
		"department": "Declaration",
	},
	{"task_subject": "Finance pays Pre-Clearance Permits", "department": "Finance"},
	{"task_subject": "Client conducts inspection", "department": "Operations"},
	{"task_subject": "Track shipment and monitor ETA", "department": "Operations"},
	{
		"task_subject": "Receive Final Clearance Documents (B/L, Invoice, PKL, COC)",
		"department": "Documentation",
	},
	{"task_subject": "Request Manifest and Local Import Charges", "department": "Documentation"},
	{"task_subject": "Create Entry (after vessel arrival confirmation)", "department": "Declaration"},
	{"task_subject": "Finance pays Shipping Line Charges", "department": "Finance"},
	{"task_subject": "Lodge Delivery Order", "department": "Operations"},
	{"task_subject": "Confirm Entry Payment (Client/CGM)", "department": "Finance"},
	{"task_subject": "Prepare and pay Post-Clearance Permits", "department": "Declaration"},
	{"task_subject": "Field Officers conduct clearance", "department": "Field Operations"},
	{"task_subject": "Supervisor obtains KPA Invoice", "department": "Operations"},
	{"task_subject": "Finance pays KPA Invoice", "department": "Finance"},
	{"task_subject": "Book trucks and notify warehouse", "department": "Transport"},
	{"task_subject": "Load trucks and exit port", "department": "Transport"},
	{"task_subject": "Monitor delivery to destination", "department": "Transport"},
	{"task_subject": "Offload cargo", "department": "Transport"},
	{"task_subject": "Return empty container to depot", "department": "Transport"},
	{"task_subject": "Receive interchange confirmation", "department": "Transport"},
]

# Visual workflow chart on Project (matches CGM Sea Import Workflow states).
TRACKING_WORKFLOW_STATES = [
	"Draft",
	"Documents Received",
	"UCR Applied",
	"UCR Paid",
	"Pre-clearance",
	"Client Inspection",
	"In Transit",
	"Final Docs Received",
	"Manifest Requested",
	"Entry Lodged",
	"Line Paid & DO Lodged",
	"Entry Paid",
	"Post-clearance",
	"Field Clearance",
	"KPA Paid",
	"In Delivery",
	"Containers Returned",
	"Completed",
]

# Minimum completed task sequence before entering each workflow state.
SEA_WORKFLOW_TASK_GATES: dict[str, int] = {
	"Documents Received": 1,
	"UCR Applied": 3,
	"UCR Paid": 4,
	"Pre-clearance": 5,
	"Client Inspection": 7,
	"In Transit": 8,
	"Final Docs Received": 9,
	"Manifest Requested": 10,
	"Entry Lodged": 11,
	"Line Paid & DO Lodged": 13,
	"Entry Paid": 14,
	"Post-clearance": 15,
	"Field Clearance": 16,
	"KPA Paid": 18,
	"In Delivery": 18,
	"Containers Returned": 23,
	"Completed": 24,
}

# Finance tasks that require Purchase Invoice + Payment Entry before completion.
SEA_PAYMENT_TASK_SEQS: frozenset[int] = frozenset({4, 6, 12, 14, 18})

# Completed at Project creation when CI/PKL were approved on Lead/Opportunity.
SEA_AUTO_COMPLETE_TASK_SEQS: frozenset[int] = frozenset({1, 2})

AUTO_COMPLETE_INTAKE_REMARK = (
	"Auto-completed at Project creation: shipment documents were received and "
	"approved on Lead/Opportunity and are already on the Project file."
)


def sea_task_count() -> int:
	return len(SEA_FREIGHT_TASK_TEMPLATE)


def is_sea_payment_task(task) -> bool:
	return (
		task.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY
		and int(task.get("custom_sequence_no") or 0) in SEA_PAYMENT_TASK_SEQS
	)


def is_sea_auto_completed_task(task) -> bool:
	return (
		task.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY
		and int(task.get("custom_sequence_no") or 0) in SEA_AUTO_COMPLETE_TASK_SEQS
	)


def is_sea_clearance_task(task) -> bool:
	return task.get("custom_task_flow_key") == SEA_TASK_FLOW_KEY


def task_should_show_documents(seq: int) -> bool:
	"""Task Documents table — not for CRM intake steps (1–2) auto-done at project create."""
	return seq not in SEA_AUTO_COMPLETE_TASK_SEQS


def task_should_show_payment_fields(seq: int) -> bool:
	return seq in SEA_PAYMENT_TASK_SEQS


def auto_complete_initial_sea_tasks(project: str) -> list[str]:
	"""Attach Project docs to tasks 1–2, then mark them Completed."""
	from frappe.utils import now_datetime

	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		carry_project_shipment_documents_to_sea_tasks,
	)

	carry_project_shipment_documents_to_sea_tasks(project)

	completed = []
	for seq in sorted(SEA_AUTO_COMPLETE_TASK_SEQS):
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
	"""Task sequences that count as done for workflow progress (incl. Task 5 invoices submitted)."""
	completed: set[int] = set()
	for row in tasks:
		seq = int(row.get("custom_sequence_no") or 0)
		if not seq:
			continue
		if row.get("status") == "Completed":
			completed.add(seq)
		elif seq == 5 and row.get("custom_permit_invoices_submitted"):
			completed.add(5)
	return completed


def derive_workflow_progress_from_tasks(
	tasks: list,
	states: list[str] | None = None,
) -> tuple[str, int]:
	"""Furthest workflow state supported by completed sea tasks (for the progress chart)."""
	states = states or TRACKING_WORKFLOW_STATES
	completed_seqs = effective_completed_task_seqs(tasks)
	if not completed_seqs:
		return "Draft", 0
	max_seq = max(completed_seqs)
	progress_status = "Documents Received"
	progress_index = states.index("Documents Received")
	for state in states:
		gate = SEA_WORKFLOW_TASK_GATES.get(state)
		if gate and max_seq >= gate:
			progress_status = state
			progress_index = states.index(state)
	return progress_status, progress_index


def sync_project_shipment_status_from_tasks(project: str) -> str | None:
	"""Advance Project workflow field when sea tasks have passed the current state."""
	if frappe.db.get_value("Project", project, "custom_mode_of_transport") != "Sea":
		return None
	tasks = frappe.get_all(
		"Task",
		filters={"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY},
		fields=["custom_sequence_no", "status", "custom_permit_invoices_submitted"],
		limit=30,
	)
	progress_status, _ = derive_workflow_progress_from_tasks(tasks)
	current = frappe.db.get_value("Project", project, "custom_shipment_status") or "Draft"
	states = TRACKING_WORKFLOW_STATES
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
	# Task 5 stays Open while Finance pays on Task 6; invoices submitted is enough to unlock Task 6.
	return [r for r in rows if not (r.seq == 5 and permit_invoices_ready(r.name))]


def get_open_sea_tasks(project: str) -> list[dict]:
	return frappe.db.sql(
		"""
		SELECT name, subject, custom_sequence_no AS seq, status
		FROM `tabTask`
		WHERE project = %s
		  AND custom_task_flow_key = %s
		  AND status NOT IN ('Completed', 'Cancelled')
		ORDER BY custom_sequence_no ASC
		""",
		(project, SEA_TASK_FLOW_KEY),
		as_dict=True,
	)


def enforce_sea_tasks_exist(project: str) -> None:
	if not frappe.db.exists(
		"Task",
		{"project": project, "custom_task_flow_key": SEA_TASK_FLOW_KEY},
	):
		frappe.throw(
			"Generate the <b>Sea Task Plan</b> on this Project first "
			f"({sea_task_count()} ordered steps)."
		)


def enforce_workflow_task_gate(project: str, new_status: str) -> None:
	"""Block workflow advance until prior sea tasks in the chart are Completed."""
	required_seq = SEA_WORKFLOW_TASK_GATES.get(new_status)
	if not required_seq:
		return
	enforce_sea_tasks_exist(project)
	if new_status == "Pre-clearance" and required_seq == 5:
		from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
			permit_invoices_ready_for_project,
		)

		if not permit_invoices_ready_for_project(project, "Pre-clearance"):
			frappe.throw(
				"Submit all permit invoices to Finance on <b>Apply for Pre-Clearance Permits</b> "
				"using <b>Notify Finance — invoices ready</b> before advancing workflow."
			)
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
	"""Return human-readable blockers when the 24-step sea chart is not fully complete."""
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


def sync_sea_task_template_to_settings() -> None:
	"""Replace CGM Shipping Settings sea task template with the 24-step chart."""
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return
	settings = frappe.get_single("CGM Shipping Settings")
	if not settings.meta.has_field("custom_sea_import_task_template"):
		return
	settings.set("custom_sea_import_task_template", [])
	for row in SEA_FREIGHT_TASK_TEMPLATE:
		settings.append("custom_sea_import_task_template", row)
	settings.save(ignore_permissions=True)
