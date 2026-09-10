"""Remove the Task Client Inspection fields.

Why: the section and its four fields (Client Notified On/By, Inspection
Confirmed On/By) showed only on Sea Import step 7, which the plan no longer has,
so they never appeared. Client Inspection stays a shipment status, and the
Project keeps its own inspection notification fields.

What: deletes the five Task Custom Fields - custom/task.json no longer carries
them and ensure_client_inspection_task_fields no longer recreates them - and
moves Task Permits, which sat after the section, up to where it started.
A field that holds data on some Task is left in place and reported.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe

SECTION = "custom_section_client_inspection"
DATA_FIELDS = (
	"custom_client_notified_on",
	"custom_client_notified_by",
	"custom_inspection_confirmed_on",
	"custom_inspection_confirmed_by",
)


def execute():
	meta = frappe.get_meta("Task")
	kept = [
		f
		for f in DATA_FIELDS
		if meta.has_field(f) and frappe.db.exists("Task", {f: ["is", "set"]})
	]
	if kept:
		print(f"Client Inspection fields hold data on some Tasks, not removed: {', '.join(kept)}")
		return

	for fieldname in (SECTION, *DATA_FIELDS):
		name = frappe.db.get_value("Custom Field", {"dt": "Task", "fieldname": fieldname})
		if name:
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)

	permits = frappe.db.get_value("Custom Field", {"dt": "Task", "fieldname": "custom_section_task_permits"})
	if permits and frappe.db.get_value("Custom Field", permits, "insert_after") in (SECTION, *DATA_FIELDS):
		frappe.db.set_value(
			"Custom Field", permits, "insert_after", "custom_verification_report_attached"
		)
	frappe.clear_cache(doctype="Task")
