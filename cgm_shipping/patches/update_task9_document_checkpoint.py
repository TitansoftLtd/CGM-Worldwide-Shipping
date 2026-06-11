"""Task 9: document checkpoint on Project — remove per-task Document requirements."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	field = "custom_sea_clearance_task_requirements"
	if not settings.meta.has_field(field):
		return

	new_rows: list[dict] = []
	changed = False
	has_checkpoint = False

	for row in settings.get(field) or []:
		seq = int(row.sequence_no or 0)
		if seq == 9 and row.requirement_type == "Document":
			changed = True
			continue
		if seq == 9 and row.requirement_type == "Document Checkpoint":
			has_checkpoint = True
		new_rows.append(
			{
				"sequence_no": row.sequence_no,
				"requirement_type": row.requirement_type,
				"value": row.value or "",
			}
		)

	if not has_checkpoint:
		new_rows.append(
			{"sequence_no": 9, "requirement_type": "Document Checkpoint", "value": ""}
		)
		changed = True

	if not changed:
		return

	settings.set(field, [])
	for row in new_rows:
		settings.append(field, row)
	settings.save(ignore_permissions=True)
	frappe.db.commit()
