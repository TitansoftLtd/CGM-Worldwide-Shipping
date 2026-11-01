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


@frappe.whitelist()
def get_project_task_documents(project: str) -> dict:
	"""Files attached to the project's tasks, newest first.

	Permission is checked against the Project. Frappe already refuses a File whose parent
	the user cannot read, but the caller names a project, so the project is what is
	checked here rather than relying on that.
	"""
	if not project:
		return {"rows": [], "total": 0}

	frappe.has_permission("Project", doc=project, throw=True)

	tasks = frappe.get_all(
		"Task", filters={"project": project}, fields=["name", "subject", "custom_task_role"]
	)
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
	"""How many task attachments a shipment has, without building the rows."""
	tasks = frappe.get_all("Task", filters={"project": project}, pluck="name")
	if not tasks:
		return 0
	return frappe.db.count(
		"File", {"attached_to_doctype": "Task", "attached_to_name": ["in", tasks]}
	)
