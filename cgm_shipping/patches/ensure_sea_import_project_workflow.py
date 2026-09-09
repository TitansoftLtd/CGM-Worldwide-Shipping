"""Ensure CGM Sea Import Workflow metadata exists for Project shipment status chart."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SEA_IMPORT_WORKFLOW_NAME,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_SEA_IMPORT_WORKFLOW_STATES,
)


def execute() -> None:
	if not frappe.db.exists("DocType", "Workflow"):
		return

	_ensure_workflow_states()

	if frappe.db.exists("Workflow", SEA_IMPORT_WORKFLOW_NAME):
		workflow = frappe.get_doc("Workflow", SEA_IMPORT_WORKFLOW_NAME)
		workflow.is_active = 1
		workflow.save(ignore_permissions=True)
		return

	workflow = frappe.new_doc("Workflow")
	workflow.workflow_name = SEA_IMPORT_WORKFLOW_NAME
	workflow.document_type = "Project"
	workflow.workflow_state_field = "custom_shipment_status"
	workflow.is_active = 1
	workflow.send_email_alert = 0
	workflow.override_status = 0

	for state_name in DEFAULT_SEA_IMPORT_WORKFLOW_STATES:
		workflow.append(
			"states",
			{
				"state": state_name,
				"doc_status": "0",
				"allow_edit": "System Manager",
				"is_optional_state": 0,
			},
		)

	workflow.insert(ignore_permissions=True)
	frappe.db.commit()


def _ensure_workflow_states() -> None:
	for state_name in DEFAULT_SEA_IMPORT_WORKFLOW_STATES:
		if frappe.db.exists("Workflow State", state_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Workflow State",
				"workflow_state_name": state_name,
				"style": "Primary",
			}
		).insert(ignore_permissions=True)
