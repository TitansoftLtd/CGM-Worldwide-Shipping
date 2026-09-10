"""Drop the step 7 and step 9 document rows from CGM Shipping Settings.

Why: the sea clearance requirements asked for INSPECT on step 7 and MANIFEST on
step 9. Sea Import no longer has either step, so the rows matched nothing - and
the app defaults no longer carry them, so every migrate would report the table
as edited.

What: deletes those two Document rows from Settings > custom_sea_clearance_task_requirements
when they still point at steps the Sea Import template does not have.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe

DEAD = {(7, "INSPECT"), (9, "MANIFEST")}


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_TEMPLATE,
	)

	if not frappe.db.table_exists("Sea Clearance Task Requirement Item"):
		return
	steps = {
		int(seq or 0)
		for seq in frappe.get_all(
			"CGM Task Template Item",
			filters={"parent": SEA_IMPORT_TEMPLATE, "parenttype": "CGM Task Template"},
			pluck="sequence_no",
		)
	}
	removed = []
	for row in frappe.get_all(
		"Sea Clearance Task Requirement Item",
		filters={"parent": "CGM Shipping Settings", "requirement_type": "Document"},
		fields=["name", "sequence_no", "value"],
	):
		key = (int(row.sequence_no or 0), (row.value or "").strip().upper())
		if key in DEAD and key[0] not in steps:
			frappe.db.delete("Sea Clearance Task Requirement Item", {"name": row.name})
			removed.append(f"{key[0]}={key[1]}")
	if removed:
		frappe.clear_document_cache("CGM Shipping Settings", "CGM Shipping Settings")
		print(f"Settings: removed document rows for missing steps: {', '.join(removed)}")
