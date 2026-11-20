"""The import charges invoice holds an air import open, like the delivery note.

The client: the invoice and the receipt come first, then you proceed to get the
delivery note. So the closing step waits for both, not the delivery note alone.

Creates the Document Type if the site lacks it, stamps the template, and brings
along live shipments that have not worked the step. A stamp a site changed for
itself is left alone.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe

ITEM = "CGM Task Template Item"
TEMPLATE = "CGM Task Template"
AIR_IMPORT = "Air Import Workflow"
FINAL_STEP = "Upload invoice for import charges and delivery note"
#: What align_air_templates_with_client_plan stamped, before the client answered.
STAMP_WAS = "Delivery Note"


def execute():
	if not frappe.db.exists("DocType", TEMPLATE):
		return
	_ensure_document_type()
	_stamp_template()
	_stamp_live_tasks()


def _wanted() -> str:
	"""The stamp the seed defines, so the plan is written down once."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		air_import_tasks,
	)

	row = next(r for r in air_import_tasks() if r["subject"] == FINAL_STEP)
	return row["required_document_types"]


def _ensure_document_type() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		ensure_document_types,
	)

	ensure_document_types()


def _is_ours(current: str | None) -> bool:
	"""Empty, or still what the earlier patch wrote. Anything else is the site's."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
		parse_required_document_types,
	)

	tokens = parse_required_document_types(current)
	return not tokens or tokens == [STAMP_WAS]


def _stamp_template() -> None:
	rows = frappe.get_all(
		ITEM,
		filters={
			"parent": AIR_IMPORT,
			"parenttype": TEMPLATE,
			"parentfield": "tasks",
			"subject": FINAL_STEP,
		},
		fields=["name", "required_document_types"],
	)
	wanted = _wanted()
	for row in rows:
		if row.required_document_types == wanted or not _is_ours(row.required_document_types):
			continue
		frappe.db.set_value(ITEM, row.name, {"required_document_types": wanted}, update_modified=False)
		print(f"{AIR_IMPORT}: {FINAL_STEP!r} now needs {wanted}")


def _stamp_live_tasks() -> None:
	tasks = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": AIR_IMPORT,
			"subject": FINAL_STEP,
			"status": ["not in", ("Completed", "Cancelled")],
		},
		fields=["name", "project", "custom_required_document_types"],
	)
	wanted = _wanted()
	for task in tasks:
		if task.custom_required_document_types == wanted or not _is_ours(
			task.custom_required_document_types
		):
			continue
		frappe.db.set_value(
			"Task", task.name, {"custom_required_document_types": wanted}, update_modified=False
		)
		print(f"{task.project}: {FINAL_STEP!r} now needs {wanted}")
