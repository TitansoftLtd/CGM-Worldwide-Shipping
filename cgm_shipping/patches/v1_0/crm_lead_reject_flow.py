"""Re-apply CRM pre-shipment workflows with lead reject action/state."""

from cgm_shipping.patches.v1_0.crm_preshipment_workflows import (
	ensure_crm_workflow_actions,
	ensure_crm_workflow_states,
	sync_preshipment_field_options,
	ensure_lead_workflow,
	ensure_opportunity_workflow,
)


def execute():
	ensure_crm_workflow_actions()
	ensure_crm_workflow_states()
	sync_preshipment_field_options()
	ensure_lead_workflow()
	ensure_opportunity_workflow()
