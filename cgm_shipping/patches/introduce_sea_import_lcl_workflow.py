"""Set up the Sea Import LCL task plan on existing sites.

Why: LCL shipments follow their own flow - Sea Import clearance, then CFS charges
and delivery to the client (files/LCL WORKFLOW.docx). New sites get all of this
from after_install; existing sites need the records added once.

What, each only when missing (nothing a site deleted or edited is touched):
- the CFS Payment Kind and CFS Invoice / CFS Receipt charge items;
- the "CFS Paid" state on CGM Sea Import Workflow, after "KPA Paid";
- the "Sea Import LCL Workflow" CGM Task Template;
- a Task Template by Cargo Type row LCL -> Sea Import LCL Workflow on each Shipment
  Type that runs Sea Import Workflow;
- the three CFS notifications and their Settings event rows;
- the CFS rows in Settings > Document responsibilities.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe

CFS_PAID = "CFS Paid"


def execute():
	_charge_items()
	_workflow_state()
	_template()
	_shipment_types()
	_notifications()
	_responsibilities()


def _charge_items():
	from cgm_shipping.cgm_worldwide_shipping.customizations.clearance_charge_item import (
		ensure_clearance_charge_items,
	)

	ensure_clearance_charge_items()


def _workflow_state():
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import SEA_IMPORT_WORKFLOW_NAME

	if not frappe.db.exists("Workflow", SEA_IMPORT_WORKFLOW_NAME):
		return
	if not frappe.db.exists("Workflow State", CFS_PAID):
		frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": CFS_PAID, "style": "Primary"}).insert(
			ignore_permissions=True
		)
	workflow = frappe.get_doc("Workflow", SEA_IMPORT_WORKFLOW_NAME)
	states = [row.state for row in workflow.states]
	if CFS_PAID in states:
		return
	template = next((row for row in workflow.states if row.state == "KPA Paid"), workflow.states[-1])
	row = workflow.append(
		"states",
		{
			"state": CFS_PAID,
			"doc_status": template.doc_status,
			"allow_edit": template.allow_edit,
			"is_optional_state": 0,
		},
	)
	# Place it right after KPA Paid so the chart order matches the flow.
	workflow.states.remove(row)
	workflow.states.insert(workflow.states.index(template) + 1, row)
	for idx, state in enumerate(workflow.states, 1):
		state.idx = idx
	workflow.save(ignore_permissions=True)


def _template():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_LCL_TEMPLATE,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		TEMPLATE_DEFINITIONS,
	)

	if frappe.db.exists("CGM Task Template", SEA_IMPORT_LCL_TEMPLATE):
		return
	definition = next(d for d in TEMPLATE_DEFINITIONS if d["template_name"] == SEA_IMPORT_LCL_TEMPLATE)
	doc = frappe.get_doc(
		{
			"doctype": "CGM Task Template",
			"template_name": SEA_IMPORT_LCL_TEMPLATE,
			"description": definition["description"],
			"is_active": 1,
		}
	)
	for task in definition["tasks"]:
		doc.append("tasks", task)
	for gate in definition["gates"]:
		doc.append("gates", gate)
	doc.insert(ignore_permissions=True)


def _shipment_types():
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_LCL_TEMPLATE,
		SEA_IMPORT_TEMPLATE,
	)

	if not frappe.db.table_exists("Shipment Type Cargo Template"):
		return
	if not frappe.db.exists("Cargo Type", "LCL") or not frappe.db.exists("CGM Task Template", SEA_IMPORT_LCL_TEMPLATE):
		return
	for name in frappe.get_all("Shipment Type", filters={"task_template": SEA_IMPORT_TEMPLATE}, pluck="name"):
		if frappe.db.exists(
			"Shipment Type Cargo Template", {"parent": name, "parenttype": "Shipment Type", "cargo_type": "LCL"}
		):
			continue
		frappe.get_doc(
			{
				"doctype": "Shipment Type Cargo Template",
				"parent": name,
				"parenttype": "Shipment Type",
				"parentfield": "cargo_type_templates",
				"idx": frappe.db.count("Shipment Type Cargo Template", {"parent": name}) + 1,
				"cargo_type": "LCL",
				"task_template": SEA_IMPORT_LCL_TEMPLATE,
			}
		).db_insert()


def _notifications():
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CFS_INVOICE_TO_FINANCE,
		CFS_RECEIPT_FOR_SUPERVISOR,
		CFS_RECEIPT_VERIFY_FINANCE,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
		ensure_sea_task_notifications,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_notifications import (
		WORKFLOW_NOTIFICATION_DEFAULTS,
		WORKFLOW_NOTIFICATIONS_FIELD,
	)

	names = (CFS_INVOICE_TO_FINANCE, CFS_RECEIPT_FOR_SUPERVISOR, CFS_RECEIPT_VERIFY_FINANCE)
	ensure_sea_task_notifications(only=names)
	if not frappe.db.table_exists("CGM Workflow Notification Item"):
		return
	field_filter = {"parent": "CGM Shipping Settings", "parentfield": WORKFLOW_NOTIFICATIONS_FIELD}
	for event, notification, notes in WORKFLOW_NOTIFICATION_DEFAULTS:
		if notification not in names or not frappe.db.exists("Notification", notification):
			continue
		if frappe.db.exists("CGM Workflow Notification Item", {**field_filter, "workflow_event": event}):
			continue
		frappe.get_doc(
			{
				"doctype": "CGM Workflow Notification Item",
				"parenttype": "CGM Shipping Settings",
				"idx": frappe.db.count("CGM Workflow Notification Item", field_filter) + 1,
				**field_filter,
				"workflow_event": event,
				"notification": notification,
				"notes": notes,
			}
		).db_insert()


def _responsibilities():
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		FLOW_CFS,
		RESPONSIBILITIES_FIELD,
		default_responsibility_rows,
	)

	if not frappe.db.table_exists("CGM Document Responsibility Item"):
		return
	field_filter = {"parent": "CGM Shipping Settings", "parentfield": RESPONSIBILITIES_FIELD}
	for row in default_responsibility_rows():
		if row["workflow_flow"] != FLOW_CFS:
			continue
		if frappe.db.exists(
			"CGM Document Responsibility Item", {**field_filter, "workflow_flow": FLOW_CFS, "action": row["action"]}
		):
			continue
		if row["role_group"] and not frappe.db.exists("CGM Role Group", row["role_group"]):
			continue
		frappe.get_doc(
			{
				"doctype": "CGM Document Responsibility Item",
				"parenttype": "CGM Shipping Settings",
				"idx": frappe.db.count("CGM Document Responsibility Item", field_filter) + 1,
				**field_filter,
				**row,
			}
		).db_insert()
	frappe.clear_document_cache("CGM Shipping Settings", "CGM Shipping Settings")
