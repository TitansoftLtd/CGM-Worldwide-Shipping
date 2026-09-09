"""Remove Manifest Requested from all clearance workflow charts.

Task 9 (Request Manifest and Local Import Charges) remains on the sea/air
task plans; only the redundant workflow pill and manual advance step are dropped.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SEA_IMPORT_WORKFLOW_NAME,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_SEA_IMPORT_WORKFLOW_STATES,
	DEFAULT_SEA_WORKFLOW_TASK_GATES,
)

REMOVED_STATE = "Manifest Requested"
BRIDGE_FROM = "Final Docs Received"
BRIDGE_TO = "Entry Lodged"
BRIDGE_ACTION = "Lodge Customs Entry"


def execute() -> None:
	_remove_manifest_from_settings_gates()
	_sync_sea_import_workflow()
	_resync_clearance_projects()
	frappe.db.commit()


def _remove_manifest_from_settings_gates() -> None:
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return
	settings = frappe.get_doc("CGM Shipping Settings")
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("custom_sea_workflow_task_gates"):
		return

	rows = list(settings.get("custom_sea_workflow_task_gates") or [])
	filtered = [
		row
		for row in rows
		if (row.shipment_workflow_state or "").strip() != REMOVED_STATE
	]
	if len(filtered) != len(rows):
		settings.set("custom_sea_workflow_task_gates", [])
		for row in filtered:
			settings.append("custom_sea_workflow_task_gates", row)
		settings.flags.skip_package_visibility_apply = True
		settings.save(ignore_permissions=True)
		return

	# Settings still on factory defaults — replace with current gate list.
	expected_states = {
		(row.get("shipment_workflow_state") or "").strip()
		for row in DEFAULT_SEA_WORKFLOW_TASK_GATES
	}
	current_states = {
		(row.shipment_workflow_state or "").strip()
		for row in rows
		if (row.shipment_workflow_state or "").strip()
	}
	if REMOVED_STATE in current_states or current_states != expected_states:
		settings.set("custom_sea_workflow_task_gates", [])
		for row in DEFAULT_SEA_WORKFLOW_TASK_GATES:
			settings.append("custom_sea_workflow_task_gates", row)
		settings.flags.skip_package_visibility_apply = True
		settings.save(ignore_permissions=True)


def _sync_sea_import_workflow() -> None:
	if not frappe.db.exists("DocType", "Workflow"):
		return
	if not frappe.db.exists("Workflow", SEA_IMPORT_WORKFLOW_NAME):
		return

	workflow = frappe.get_doc("Workflow", SEA_IMPORT_WORKFLOW_NAME)
	workflow.is_active = 1

	existing_states = [row.state for row in workflow.states if row.state]
	desired_states = list(DEFAULT_SEA_IMPORT_WORKFLOW_STATES)

	bridge_action = BRIDGE_ACTION
	bridge_allowed = "System Manager"
	new_transitions: list[dict] = []
	has_bridge = False
	for row in workflow.transitions or []:
		state = (row.state or "").strip()
		next_state = (row.next_state or "").strip()
		if state == REMOVED_STATE or next_state == REMOVED_STATE:
			if state == REMOVED_STATE:
				bridge_action = (row.action or "").strip() or BRIDGE_ACTION
				bridge_allowed = row.allowed or bridge_allowed
			continue
		if state == BRIDGE_FROM and next_state == BRIDGE_TO:
			has_bridge = True
		new_transitions.append(
			{
				"state": state,
				"action": row.action,
				"next_state": next_state,
				"allowed": row.allowed,
				"allow_self_approval": row.allow_self_approval,
			}
		)

	if not has_bridge:
		new_transitions.append(
			{
				"state": BRIDGE_FROM,
				"action": bridge_action,
				"next_state": BRIDGE_TO,
				"allowed": bridge_allowed,
				"allow_self_approval": 1,
			}
		)

	needs_save = (
		REMOVED_STATE in existing_states
		or existing_states != desired_states
		or any(
			(row.state or "").strip() == REMOVED_STATE
			or (row.next_state or "").strip() == REMOVED_STATE
			for row in (workflow.transitions or [])
		)
		or not has_bridge
	)
	if not needs_save:
		return

	workflow.states = []
	for state_name in desired_states:
		workflow.append(
			"states",
			{
				"state": state_name,
				"doc_status": "0",
				"allow_edit": "System Manager",
				"is_optional_state": 0,
			},
		)

	workflow.transitions = []
	for row in new_transitions:
		workflow.append("transitions", row)

	workflow.save(ignore_permissions=True)


def _resync_clearance_projects() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
		sync_project_shipment_status_from_tasks,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
		get_clearance_workflow_states_for_project,
		project_uses_clearance_workflow_states,
	)

	stuck = frappe.get_all(
		"Project",
		filters={"custom_shipment_status": REMOVED_STATE},
		pluck="name",
		limit=500,
	)
	for name in stuck:
		frappe.db.set_value(
			"Project",
			name,
			"custom_shipment_status",
			BRIDGE_FROM,
			update_modified=False,
		)
		if frappe.get_meta("Project").has_field("workflow_state"):
			frappe.db.set_value(
				"Project",
				name,
				"workflow_state",
				BRIDGE_FROM,
				update_modified=False,
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
			states = get_clearance_workflow_states_for_project(proj)
			current = (proj.get("custom_shipment_status") or "").strip()
			if current and current not in states:
				frappe.db.set_value(
					"Project",
					name,
					"custom_shipment_status",
					"Draft",
					update_modified=False,
				)
			if sync_project_shipment_status_from_tasks(name):
				updated += 1
		except Exception:
			frappe.log_error(title=f"CGM: manifest removal resync failed for {name}")
	if updated:
		frappe.logger("cgm_shipping").info(
			f"Resynced shipment workflow status on {updated} project(s) after removing Manifest Requested"
		)
