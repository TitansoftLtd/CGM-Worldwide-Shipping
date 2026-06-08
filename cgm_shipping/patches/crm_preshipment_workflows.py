"""CRM pre-shipment setup: roles + Lead/Opportunity status fields.

The Lead/Opportunity workflows, their states and actions are installed from
``fixtures`` (workflow.json / workflow_state.json / workflow_action_master.json),
so this patch only seeds the roles and custom status fields they depend on.
"""

import frappe


def execute():
	ensure_crm_roles()
	ensure_lead_preshipment_field()
	ensure_opportunity_preshipment_field()
	sync_preshipment_field_options()
	migrate_legacy_preshipment_states()


def ensure_crm_roles():
	for role_name in ["CGM Documentation", "Operations Manager"]:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)


def ensure_lead_preshipment_field():
	options = "\n".join(["Lead Intake", "Lead Docs Verified", "Lead Docs Rejected", "Lead Ready to Convert"])
	create_custom_field(
		"Lead",
		{
			"fieldname": "custom_cgm_preshipment_status",
			"label": "CGM Pre-Shipment Status",
			"fieldtype": "Select",
			"options": options,
			"default": "Lead Intake",
			"insert_after": "status",
			"description": "Workflow: new prospect document gate before converting to Customer.",
		},
	)


def ensure_opportunity_preshipment_field():
	options = "\n".join(["Opp Intake", "Opp Docs Verified", "Opp Docs Rejected", "Opp Ready for Project"])
	create_custom_field(
		"Opportunity",
		{
			"fieldname": "custom_cgm_preshipment_status",
			"label": "CGM Pre-Shipment Status",
			"fieldtype": "Select",
			"options": options,
			"default": "Opp Intake",
			"insert_after": "status",
			"description": "Workflow: repeat-customer document gate before creating a shipment Project.",
		},
	)


def create_custom_field(dt, values):
	field_name = f"{dt}-{values['fieldname']}"
	if frappe.db.exists("Custom Field", field_name):
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	for key, value in values.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)


def sync_preshipment_field_options():
	for dt, options in (
		("Lead", "\n".join(["Lead Intake", "Lead Docs Verified", "Lead Docs Rejected", "Lead Ready to Convert"])),
		("Opportunity", "\n".join(["Opp Intake", "Opp Docs Verified", "Opp Docs Rejected", "Opp Ready for Project"])),
	):
		cf_name = f"{dt}-custom_cgm_preshipment_status"
		if frappe.db.exists("Custom Field", cf_name):
			cf = frappe.get_doc("Custom Field", cf_name)
			cf.options = options
			cf.save(ignore_permissions=True)


def migrate_legacy_preshipment_states():
	frappe.db.sql(
		"""
		UPDATE `tabLead`
		SET custom_cgm_preshipment_status = 'Lead Docs Verified'
		WHERE custom_cgm_preshipment_status = 'Lead Docs Received'
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabOpportunity`
		SET custom_cgm_preshipment_status = 'Opp Docs Verified'
		WHERE custom_cgm_preshipment_status = 'Opp Docs Received'
		"""
	)
	frappe.db.commit()
