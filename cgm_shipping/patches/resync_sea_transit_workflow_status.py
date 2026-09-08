"""Re-sync Sea Transit Import projects onto the lean transit workflow chart.

Sea Transit projects previously reused the full Sea Import status pills (including
Manifest Requested). After switching to transit-specific gates, realign status
from completed tasks.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		sync_project_shipment_status_from_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_TRANSIT_IMPORT_TEMPLATE,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
		get_clearance_workflow_states_for_project,
		project_is_sea_transit_import,
	)

	projects = frappe.get_all(
		"Project",
		filters={"custom_shipment_type": "Sea Transit"},
		pluck="name",
		limit=2000,
	)
	updated = 0
	for name in projects:
		try:
			proj = frappe.get_doc("Project", name)
			if not project_is_sea_transit_import(proj):
				continue
			states = get_clearance_workflow_states_for_project(proj)
			current = (proj.get("custom_shipment_status") or "").strip()
			if current and current not in states and current != "Draft":
				frappe.db.set_value(
					"Project",
					name,
					"custom_shipment_status",
					"Draft",
					update_modified=False,
				)
				if frappe.get_meta("Project").has_field("workflow_state"):
					frappe.db.set_value(
						"Project",
						name,
						"workflow_state",
						"Draft",
						update_modified=False,
					)
			if sync_project_shipment_status_from_tasks(name):
				updated += 1
		except Exception:
			frappe.log_error(title=f"CGM: sea transit workflow resync failed for {name}")
	if updated:
		frappe.logger("cgm_shipping").info(
			f"Resynced sea transit workflow status on {updated} project(s) "
			f"({SEA_TRANSIT_IMPORT_TEMPLATE})"
		)
