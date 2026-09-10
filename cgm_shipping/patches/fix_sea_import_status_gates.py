"""Sea Import status gates: In Delivery on step 21, no Client Inspection gate.

Why: In Delivery was reached by step 19 (Finance pays KPA Invoice), so a shipment
showed In Delivery as soon as KPA was paid; it now waits for step 21 (Load trucks
and exit port). Client Inspection pointed at step 7, which the plan no longer
has, so it could never be reached - the gate is dropped and the status stays on
the chart without one.

What: on the Sea Import template, moves an In Delivery gate still on step 19 to
step 21 and deletes a Client Inspection gate whose step is not in the plan, then
resyncs the status of projects sitting on In Delivery - those whose trucks have
not left the port go back to KPA Paid.

Idempotent: rows already changed are left alone. One-time - retire per
docs/guides/patches.md once staging and production Patch Log show it.
"""

import frappe

IN_DELIVERY = "In Delivery"
CLIENT_INSPECTION = "Client Inspection"
OLD_IN_DELIVERY_STEP = 19
NEW_IN_DELIVERY_STEP = 21


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		sync_project_shipment_status_from_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_TEMPLATE,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_gates import (
		GATE_DOCTYPE,
		task_subjects_by_sequence,
	)

	if not frappe.db.table_exists(GATE_DOCTYPE):
		return
	if not frappe.db.exists("CGM Task Template", SEA_IMPORT_TEMPLATE):
		return

	subjects = task_subjects_by_sequence(
		frappe.get_all(
			"CGM Task Template Item",
			filters={"parent": SEA_IMPORT_TEMPLATE, "parenttype": "CGM Task Template"},
			fields=["sequence_no", "subject"],
		)
	)
	changed = []
	for gate in frappe.get_all(
		GATE_DOCTYPE,
		filters={"parent": SEA_IMPORT_TEMPLATE, "parenttype": "CGM Task Template"},
		fields=["name", "shipment_workflow_state", "min_completed_task_seq"],
	):
		seq = int(gate.min_completed_task_seq or 0)
		if (
			gate.shipment_workflow_state == IN_DELIVERY
			and seq == OLD_IN_DELIVERY_STEP
			and NEW_IN_DELIVERY_STEP in subjects
		):
			frappe.db.set_value(
				GATE_DOCTYPE,
				gate.name,
				{
					"min_completed_task_seq": NEW_IN_DELIVERY_STEP,
					"task_subject": subjects[NEW_IN_DELIVERY_STEP],
				},
				update_modified=False,
			)
			changed.append(f"{IN_DELIVERY} -> step {NEW_IN_DELIVERY_STEP}")
		elif gate.shipment_workflow_state == CLIENT_INSPECTION and seq not in subjects:
			frappe.db.delete(GATE_DOCTYPE, {"name": gate.name})
			changed.append(f"{CLIENT_INSPECTION} gate removed")
	if not changed:
		return

	# A migrate is one request: gate rows read earlier in it are cached.
	if getattr(frappe.local, "request_cache", None) is not None:
		frappe.local.request_cache.clear()
	frappe.clear_document_cache("CGM Task Template", SEA_IMPORT_TEMPLATE)

	moved = []
	for project in frappe.get_all(
		"Project", filters={"custom_shipment_status": IN_DELIVERY}, pluck="name"
	):
		status = sync_project_shipment_status_from_tasks(project)
		if status:
			moved.append(f"{project} -> {status}")
	print(f"Sea Import gates: {', '.join(changed)}. Status resynced: {', '.join(moved) or 'none'}")
