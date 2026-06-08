import frappe


WORKFLOW_NAME = "CGM Sea Import Workflow"


def execute():
	ensure_roles()
	ensure_workflow_actions()
	ensure_workflow_states()
	ensure_project_fields()
	ensure_workflow()


def ensure_roles():
	for role_name in ["Operations Manager", "Declarant", "Finance Manager", "Field Officer", "Transport Manager"]:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)


def ensure_workflow_actions():
	for action_name in [
		"Approve Docs & Create IDF",
		"Start Permits",
		"Permits Ready",
		"Mark Arrived",
		"Start Clearing",
		"Release Cargo",
		"Dispatch Truck",
		"Confirm Delivery",
		"Start Container Return",
		"Confirm Interchange & Close",
	]:
		if not frappe.db.exists("Workflow Action Master", action_name):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action_name}).insert(
				ignore_permissions=True
			)


def ensure_workflow_states():
	state_styles = {
		"Documents Received": "Warning",
		"IDF Created": "Primary",
		"Permits Processing": "Primary",
		"Awaiting Arrival": "Info",
		"Arrived": "Info",
		"Clearing": "Warning",
		"Released": "Primary",
		"In Transit": "Info",
		"Delivered": "Success",
		"Container Return Pending": "Warning",
		"Completed": "Success",
	}
	for state_name, style in state_styles.items():
		if frappe.db.exists("Workflow State", state_name):
			state_doc = frappe.get_doc("Workflow State", state_name)
			if state_doc.style != style:
				state_doc.style = style
				state_doc.save(ignore_permissions=True)
			continue
		frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state_name, "style": style}).insert(
			ignore_permissions=True
		)


def ensure_project_fields():
	# Step 1: create clear ETD/ETA fields if they don't exist yet.
	create_custom_field(
		"Project",
		{
			"fieldname": "custom_etd",
			"label": "Expected Time of Departure (ETD)",
			"fieldtype": "Date",
			"insert_after": "expected_start_date",
		},
	)
	create_custom_field(
		"Project",
		{
			"fieldname": "custom_eta",
			"label": "Expected Time of Arrival (ETA)",
			"fieldtype": "Date",
			"insert_after": "expected_end_date",
		},
	)

	# Step 2: ensure shipment status options include container return state.
	status_field_name = "Project-custom_shipment_status"
	if frappe.db.exists("Custom Field", status_field_name):
		status_field = frappe.get_doc("Custom Field", status_field_name)
		required_state = "Container Return Pending"
		current_options = (status_field.options or "").split("\n")
		if required_state not in current_options:
			current_options.append(required_state)
			status_field.options = "\n".join(opt for opt in current_options if opt)
			status_field.save(ignore_permissions=True)


def create_custom_field(dt, values):
	field_name = f"{dt}-{values['fieldname']}"
	if frappe.db.exists("Custom Field", field_name):
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	for key, value in values.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)


def ensure_workflow():
	# Step 2: rebuild workflow from source of truth.
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		frappe.delete_doc("Workflow", WORKFLOW_NAME, ignore_permissions=True, force=True)

	workflow = frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW_NAME,
			"document_type": "Project",
			"is_active": 1,
			"workflow_state_field": "custom_shipment_status",
			"send_email_alert": 0,
			"states": [
				{"state": "Documents Received", "doc_status": "0", "allow_edit": "Operations Manager"},
				{"state": "IDF Created", "doc_status": "0", "allow_edit": "Declarant"},
				{"state": "Permits Processing", "doc_status": "0", "allow_edit": "Declarant"},
				{"state": "Awaiting Arrival", "doc_status": "0", "allow_edit": "Operations Manager"},
				{"state": "Arrived", "doc_status": "0", "allow_edit": "Operations Manager"},
				{"state": "Clearing", "doc_status": "0", "allow_edit": "Field Officer"},
				{"state": "Released", "doc_status": "0", "allow_edit": "Field Officer"},
				{"state": "In Transit", "doc_status": "0", "allow_edit": "Transport Manager"},
				{"state": "Delivered", "doc_status": "0", "allow_edit": "Transport Manager"},
				{"state": "Container Return Pending", "doc_status": "0", "allow_edit": "Transport Manager"},
				{"state": "Completed", "doc_status": "0", "allow_edit": "Operations Manager"},
			],
			"transitions": [
				{
					"state": "Documents Received",
					"action": "Approve Docs & Create IDF",
					"next_state": "IDF Created",
					"allowed": "Declarant",
					"allow_self_approval": 1,
				},
				{
					"state": "IDF Created",
					"action": "Start Permits",
					"next_state": "Permits Processing",
					"allowed": "Declarant",
					"allow_self_approval": 1,
				},
				{
					"state": "Permits Processing",
					"action": "Permits Ready",
					"next_state": "Awaiting Arrival",
					"allowed": "Finance Manager",
					"allow_self_approval": 1,
				},
				{
					"state": "Awaiting Arrival",
					"action": "Mark Arrived",
					"next_state": "Arrived",
					"allowed": "Operations Manager",
					"allow_self_approval": 1,
				},
				{
					"state": "Arrived",
					"action": "Start Clearing",
					"next_state": "Clearing",
					"allowed": "Field Officer",
					"allow_self_approval": 1,
				},
				{
					"state": "Clearing",
					"action": "Release Cargo",
					"next_state": "Released",
					"allowed": "Field Officer",
					"allow_self_approval": 1,
				},
				{
					"state": "Released",
					"action": "Dispatch Truck",
					"next_state": "In Transit",
					"allowed": "Transport Manager",
					"allow_self_approval": 1,
				},
				{
					"state": "In Transit",
					"action": "Confirm Delivery",
					"next_state": "Delivered",
					"allowed": "Transport Manager",
					"allow_self_approval": 1,
				},
				{
					"state": "Delivered",
					"action": "Start Container Return",
					"next_state": "Container Return Pending",
					"allowed": "Transport Manager",
					"allow_self_approval": 1,
				},
				{
					"state": "Container Return Pending",
					"action": "Confirm Interchange & Close",
					"next_state": "Completed",
					"allowed": "Operations Manager",
					"allow_self_approval": 1,
				},
			],
		}
	)
	workflow.insert(ignore_permissions=True)
