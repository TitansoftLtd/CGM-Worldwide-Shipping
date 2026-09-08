"""Rewind Project shipment status when clearance tasks are still open."""

from __future__ import annotations


def execute():
	import frappe

	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		sync_project_shipment_status_from_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
		project_uses_clearance_workflow_states,
	)

	projects = frappe.get_all(
		"Project",
		filters={"custom_shipment_status": "Completed"},
		pluck="name",
	)
	for name in projects:
		try:
			proj = frappe.get_doc("Project", name)
			if not project_uses_clearance_workflow_states(proj):
				continue
			sync_project_shipment_status_from_tasks(name)
		except Exception:
			frappe.log_error(title=f"CGM: failed to rewind Completed status for {name}")
