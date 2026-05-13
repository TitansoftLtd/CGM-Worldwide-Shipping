import frappe

from cgm_shipping.patches.v1_0.seed_cgm_shipping_settings_templates import DEFAULT_WORKFLOW_STAGE_ROWS


def execute():
	"""Sites where seed ran before workflow gates existed: fill child table once."""
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("custom_workflow_stage_requirements"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	if settings.get("custom_workflow_stage_requirements"):
		return

	for row in DEFAULT_WORKFLOW_STAGE_ROWS:
		settings.append("custom_workflow_stage_requirements", row)

	settings.save(ignore_permissions=True)
	frappe.db.commit()
