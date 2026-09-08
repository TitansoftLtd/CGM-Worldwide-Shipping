"""Re-sync Project shipment status after gate-based workflow progress fix.

Projects stuck at UCR Applied (or similar) while all tasks are Completed used
contiguous-sequence progress; this re-runs sync with per-gate + all-complete logic.
"""

from __future__ import annotations

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		sync_project_shipment_status_from_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
		project_uses_clearance_workflow_states,
	)

	projects = frappe.get_all(
		"Project",
		filters={"custom_shipment_status": ["!=", ""]},
		pluck="name",
		limit=2000,
	)
	updated = 0
	for name in projects:
		try:
			proj = frappe.get_doc("Project", name)
			if not project_uses_clearance_workflow_states(proj):
				continue
			if sync_project_shipment_status_from_tasks(name):
				updated += 1
		except Exception:
			frappe.log_error(title=f"CGM: workflow status resync failed for {name}")
	if updated:
		frappe.logger("cgm_shipping").info(
			f"Resynced shipment workflow status on {updated} project(s)"
		)
