import frappe

from cgm_shipping.patches.v1_0.seed_cgm_shipping_settings_templates import DEFAULT_WORKFLOW_STAGE_ROWS


def execute():
	"""Sites where workflow gates were added after sea task seed: fill workflow table once."""
	from cgm_shipping.patches.v1_0.seed_cgm_shipping_settings_templates import execute as seed_settings

	seed_settings()
