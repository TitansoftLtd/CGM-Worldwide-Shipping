"""Fix Task Permits table hidden on post-clearance Finance tasks (sequence 16).

Root cause: ``custom_task_permits`` / ``custom_section_task_permits`` depended on
``[5, 6, 15]`` only, so sequence 16 (Finance pays for Post-Clearance Permits) failed
Desk ``depends_on`` before task.js could override it — Finance saw no permit invoices
even when the child rows existed in the database.

Idempotent: yes — updates Custom Field depends_on when it still matches the old rule.
"""

from __future__ import annotations

import frappe

TASK_PERMITS_DEPENDS_ON = (
	"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && "
	"(['Permit Application','Permit Finance'].includes(doc.custom_task_role) || "
	"doc.custom_requires_permit_action || [5,6,15,16].includes(doc.custom_sequence_no))"
)

OLD_DEPENDS_ON = (
	"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && "
	"[5,6,15].includes(doc.custom_sequence_no)"
)

FIELDNAMES = ("custom_section_task_permits", "custom_task_permits")


def execute():
	for fieldname in FIELDNAMES:
		name = f"Task-{fieldname}"
		if not frappe.db.exists("Custom Field", name):
			continue
		current = frappe.db.get_value("Custom Field", name, "depends_on") or ""
		if current in (TASK_PERMITS_DEPENDS_ON, ""):
			continue
		if current != OLD_DEPENDS_ON and "[5,6,15]" not in current:
			continue
		frappe.db.set_value("Custom Field", name, "depends_on", TASK_PERMITS_DEPENDS_ON)
	frappe.clear_cache(doctype="Task")
