"""Workflows the app's code depends on, created on migrate when missing.

Only a missing workflow is created. An existing one - its states, transitions,
roles, even whether it is active - is left exactly as the desk has it. The
Sales Invoice approval workflow lives in sales_invoice_workflow.py.

CGM Quotation Approval is deliberately not created here: production removed
it, and migrate must not bring it back.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_IMPORT_WORKFLOW_NAME


def ensure_app_workflows() -> None:
	if not frappe.db.exists("DocType", "Workflow"):
		return
	ensure_sea_import_project_workflow()
	frappe.db.commit()


def _ensure_workflow_states(names) -> None:
	for state_name in names:
		if frappe.db.exists("Workflow State", state_name):
			continue
		frappe.get_doc(
			{"doctype": "Workflow State", "workflow_state_name": state_name, "style": "Primary"}
		).insert(ignore_permissions=True)


def ensure_sea_import_project_workflow() -> None:
	"""CGM Sea Import Workflow: the Project shipment status chart's states."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
		DEFAULT_SEA_IMPORT_WORKFLOW_STATES,
	)

	_ensure_workflow_states(DEFAULT_SEA_IMPORT_WORKFLOW_STATES)
	if frappe.db.exists("Workflow", SEA_IMPORT_WORKFLOW_NAME):
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
			{"state": state_name, "doc_status": "0", "allow_edit": "System Manager", "is_optional_state": 0},
		)
	workflow.insert(ignore_permissions=True)
