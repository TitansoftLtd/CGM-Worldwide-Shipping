import frappe


WORKFLOW_LEAD = "CGM Lead Pre-Shipment"
WORKFLOW_OPP = "CGM Opportunity Pre-Shipment"


def execute():
	ensure_crm_roles()
	ensure_crm_workflow_actions()
	ensure_crm_workflow_states()
	ensure_lead_preshipment_field()
	ensure_opportunity_preshipment_field()
	sync_preshipment_field_options()
	migrate_legacy_preshipment_states()
	ensure_lead_workflow()
	ensure_opportunity_workflow()


def ensure_crm_roles():
	for role_name in ["CGM Documentation", "Operations Manager"]:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)


def ensure_crm_workflow_actions():
	for action_name in [
		"Approve CI/PKL",
		"Authorize Customer Creation",
		"Authorize Shipment File",
	]:
		if not frappe.db.exists("Workflow Action Master", action_name):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action_name}).insert(
				ignore_permissions=True
			)


def ensure_crm_workflow_states():
	for state_name, style in [
		("Lead Intake", "Warning"),
		("Lead Docs Verified", "Success"),
		("Lead Ready to Convert", "Success"),
		("Opp Intake", "Warning"),
		("Opp Docs Verified", "Success"),
		("Opp Ready for Project", "Success"),
	]:
		if not frappe.db.exists("Workflow State", state_name):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state_name, "style": style}
			).insert(ignore_permissions=True)


def ensure_lead_preshipment_field():
	options = "\n".join(["Lead Intake", "Lead Docs Verified", "Lead Ready to Convert"])
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
	options = "\n".join(["Opp Intake", "Opp Docs Verified", "Opp Ready for Project"])
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
		("Lead", "\n".join(["Lead Intake", "Lead Docs Verified", "Lead Ready to Convert"])),
		("Opportunity", "\n".join(["Opp Intake", "Opp Docs Verified", "Opp Ready for Project"])),
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


def ensure_lead_workflow():
	if frappe.db.exists("Workflow", WORKFLOW_LEAD):
		frappe.delete_doc("Workflow", WORKFLOW_LEAD, ignore_permissions=True, force=True)

	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW_LEAD,
			"document_type": "Lead",
			"is_active": 1,
			"workflow_state_field": "custom_cgm_preshipment_status",
			"send_email_alert": 0,
			"states": [
				{"state": "Lead Intake", "doc_status": "0", "allow_edit": "All"},
				{"state": "Lead Docs Verified", "doc_status": "0", "allow_edit": "Operations Manager"},
				{"state": "Lead Ready to Convert", "doc_status": "0", "allow_edit": "Operations Manager"},
			],
			"transitions": [
				{
					"state": "Lead Intake",
					"action": "Approve CI/PKL",
					"next_state": "Lead Docs Verified",
					"allowed": "Operations Manager",
					"allow_self_approval": 1,
				},
				{
					"state": "Lead Docs Verified",
					"action": "Authorize Customer Creation",
					"next_state": "Lead Ready to Convert",
					"allowed": "Operations Manager",
					"allow_self_approval": 1,
				},
			],
		}
	)
	workflow.insert(ignore_permissions=True)


def ensure_opportunity_workflow():
	if frappe.db.exists("Workflow", WORKFLOW_OPP):
		frappe.delete_doc("Workflow", WORKFLOW_OPP, ignore_permissions=True, force=True)

	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW_OPP,
			"document_type": "Opportunity",
			"is_active": 1,
			"workflow_state_field": "custom_cgm_preshipment_status",
			"send_email_alert": 0,
			"states": [
				{"state": "Opp Intake", "doc_status": "0", "allow_edit": "All"},
				{"state": "Opp Docs Verified", "doc_status": "0", "allow_edit": "Operations Manager"},
				{"state": "Opp Ready for Project", "doc_status": "0", "allow_edit": "Operations Manager"},
			],
			"transitions": [
				{
					"state": "Opp Intake",
					"action": "Approve CI/PKL",
					"next_state": "Opp Docs Verified",
					"allowed": "Operations Manager",
					"allow_self_approval": 1,
				},
				{
					"state": "Opp Docs Verified",
					"action": "Authorize Shipment File",
					"next_state": "Opp Ready for Project",
					"allowed": "Operations Manager",
					"allow_self_approval": 1,
				},
			],
		}
	)
	workflow.insert(ignore_permissions=True)
