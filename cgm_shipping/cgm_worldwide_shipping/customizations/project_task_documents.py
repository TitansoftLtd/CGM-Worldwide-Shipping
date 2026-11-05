"""Every file attached to a shipment's tasks, gathered onto the shipment.

Frappe's attachments belong to the one document they were attached to, so a receipt
attached to a task is reachable only from that task. On this site that is where the work
actually lands: 2,250 files sit on tasks against 10 on projects. Someone retracing a
shipment months later, to establish which transporter returned a container late, has no
way to see them without opening each task in turn.

This gathers them for reading. It deliberately does not copy anything: duplicating the
files would double the storage and leave two versions of the truth, and a copy made today
would not notice a file replaced on the task tomorrow. The task stays the owner, and the
shipment gets the view.
"""

from __future__ import annotations

import frappe
from frappe import _


# Tasks whose attachments are payment evidence: the POP, the bank receipt, the
# proof Finance files. Everything else on a shipment - permits, certificates, the
# entry, the IDF, the supplier invoices - is the pack the job is run from.
FINANCE_TASK_ROLES = ("Finance Payment", "Permit Finance")


def _project_tasks(project: str) -> list:
	"""Every task on the shipment. Visibility is decided below, per task role."""
	return frappe.get_all(
		"Task",
		filters={"project": project},
		fields=["name", "subject", "custom_task_role"],
	)


def _readable_task_names(project: str) -> set:
	"""The project's tasks this user may open. get_list applies Task permissions."""
	if not frappe.has_permission("Task"):
		return set()
	return {
		t.name
		for t in frappe.get_list(
			"Task",
			filters={"project": project},
			fields=["name"],
			limit_page_length=0,
			ignore_permissions=False,
		)
	}


def _visible_project_tasks(project: str) -> list:
	"""Tasks whose attachments this user may see on the shipment.

	Task row visibility is scoped by department, and inheriting that here was wrong
	for this panel: every permit, IDF and entry on a shipment sits on a Declaration
	task, so a field officer - the person who carries those papers - saw an empty
	list and was told the documents did not exist.

	The shipment's pack is for whoever works the shipment. Finance's payment
	evidence is not: those stay behind the task permission, so a POP still only
	reaches someone who can open the task that holds it.
	"""
	tasks = _project_tasks(project)
	if not tasks:
		return []
	readable = _readable_task_names(project)
	return [
		t
		for t in tasks
		if (t.get("custom_task_role") or "") not in FINANCE_TASK_ROLES
		or t.name in readable
	]


@frappe.whitelist()
def get_project_task_documents(project: str) -> dict:
	"""Files attached to the shipment's tasks, newest first.

	Permission is checked on the shipment, then per task: see _visible_project_tasks.
	"""
	if not project:
		return {"rows": [], "total": 0}

	frappe.has_permission("Project", doc=project, throw=True)

	tasks = _visible_project_tasks(project)
	if not tasks:
		return {"rows": [], "total": 0}

	by_name = {t.name: t for t in tasks}
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Task", "attached_to_name": ["in", list(by_name)]},
		fields=["name", "file_name", "file_url", "is_private", "attached_to_name", "owner", "creation"],
		order_by="creation desc",
	)

	rows = []
	for f in files:
		task = by_name.get(f.attached_to_name)
		rows.append(
			{
				"file_name": f.file_name,
				"file_url": f.file_url,
				"is_private": f.is_private,
				"task": f.attached_to_name,
				"task_subject": (task.subject if task else "") or "",
				"task_role": (task.custom_task_role if task else "") or "",
				"uploaded_by": f.owner,
				"uploaded_on": f.creation,
			}
		)

	return {"rows": rows, "total": len(rows)}


def task_document_count(project: str) -> int:
	"""How many of the shipment's task attachments the user may see."""
	if not project:
		return 0
	tasks = [t.name for t in _visible_project_tasks(project)]
	if not tasks:
		return 0
	return frappe.db.count(
		"File", {"attached_to_doctype": "Task", "attached_to_name": ["in", tasks]}
	)
