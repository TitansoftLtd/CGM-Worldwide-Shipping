"""Show Task Permits table on Finance pays Pre-Clearance Permits (seq 6)."""
from __future__ import annotations

import frappe

PERMIT_DEPENDS_ON = (
	"eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E' && [5,6,15].includes(doc.custom_sequence_no)"
)

PERMIT_FIELDS = (
	"custom_section_task_permits",
	"custom_task_permits",
)


def execute():
	for fieldname in PERMIT_FIELDS:
		cf_name = f"Task-{fieldname}"
		if frappe.db.exists("Custom Field", cf_name):
			frappe.db.set_value(
				"Custom Field",
				cf_name,
				"depends_on",
				PERMIT_DEPENDS_ON,
				update_modified=False,
			)
	frappe.clear_cache(doctype="Task")
