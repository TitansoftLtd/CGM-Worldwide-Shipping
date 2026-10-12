"""Move the shipment status gates onto their CGM Task Templates.

Why: the gates lived in CGM Shipping Settings (Sea Import) and in Python tables
(Sea Transit Import, Road Transit Inbound, Air Import, Air Export), away from the
task steps they point at, so renumbering a template left them on the wrong step.
Each template now has its own Shipment Status Gates table.

What: fills that table on each template that has none. Sea Import takes the
CGM Shipping Settings rows, site edits included; the others take the defaults
that were in code. The Settings table is no longer read.

Idempotent: a template that already has gates is left alone. One-time - retire
per docs/guides/patches.md once staging and production Patch Log show it, then
delete the Sea Workflow Task Gate Item doctype.
"""

import frappe

LEGACY_DOCTYPE = "Sea Workflow Task Gate Item"


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SHIPMENT_STATUSES
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_TEMPLATE,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		TEMPLATE_DEFINITIONS,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_gates import (
		GATE_DOCTYPE,
		GATE_RULE_STANDARD,
		task_subjects_by_sequence,
	)

	if not frappe.db.table_exists(GATE_DOCTYPE):
		return

	settings_rows = []
	if frappe.db.table_exists(LEGACY_DOCTYPE):
		settings_rows = frappe.get_all(
			LEGACY_DOCTYPE,
			filters={
				"parent": "CGM Shipping Settings",
				"parentfield": "custom_sea_workflow_task_gates",
			},
			fields=["shipment_workflow_state", "min_completed_task_seq", "gate_rule"],
			order_by="idx asc",
		)
		# A site that never ran remove_manifest_requested_workflow_state still has
		# Manifest Requested here, and it is no longer a shipment status.
		settings_rows = [r for r in settings_rows if r.shipment_workflow_state in SHIPMENT_STATUSES]

	for definition in TEMPLATE_DEFINITIONS:
		name = definition["template_name"]
		rows = settings_rows if name == SEA_IMPORT_TEMPLATE and settings_rows else definition.get("gates")
		if not rows or not frappe.db.exists("CGM Task Template", name):
			continue
		if frappe.db.exists(GATE_DOCTYPE, {"parent": name, "parenttype": "CGM Task Template"}):
			continue

		subjects = task_subjects_by_sequence(
			frappe.get_all(
				"CGM Task Template Item",
				filters={"parent": name, "parenttype": "CGM Task Template"},
				fields=["sequence_no", "subject"],
			)
		)
		for idx, row in enumerate(rows, start=1):
			seq = int(row.get("min_completed_task_seq") or 0)
			frappe.get_doc(
				{
					"doctype": GATE_DOCTYPE,
					"parent": name,
					"parenttype": "CGM Task Template",
					"parentfield": "gates",
					"idx": idx,
					"shipment_workflow_state": row.get("shipment_workflow_state"),
					"min_completed_task_seq": seq,
					"task_subject": subjects.get(seq, ""),
					"gate_rule": row.get("gate_rule") or GATE_RULE_STANDARD,
				}
			).db_insert()
		print(f"Shipment status gates: {len(rows)} rows on {name}")
