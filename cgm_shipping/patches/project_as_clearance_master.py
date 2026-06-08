"""Use Project + Task as clearance master; link guide doctypes to Project.

The CGM Sea Import Workflow is installed from ``fixtures`` (workflow.json), so
this patch no longer syncs it - it only migrates Shipment Dossiers to Projects.
"""
from __future__ import annotations

import frappe

NEW_STATUS_OPTIONS = "\n".join(
	[
		"Draft",
		"Documents Received",
		"UCR Applied",
		"UCR Paid",
		"Pre-clearance",
		"Client Inspection",
		"In Transit",
		"Final Docs Received",
		"Manifest Requested",
		"Entry Lodged",
		"Line Paid & DO Lodged",
		"Entry Paid",
		"Post-clearance",
		"Field Clearance",
		"KPA Paid",
		"In Delivery",
		"Containers Returned",
		"Completed",
	]
)

LINKED_DOCTYPES = (
	"IDF UCR Record",
	"Customs Entry",
	"Container Tracker",
	"Shipping Line Charges",
	"Port Charges KPA Invoice",
	"Seal Record",
	"Export Shipment",
	"Interchange Receipt",
)

STATUS_MAP = {
	"IDF Open": "UCR Applied",
	"Taxes Paid": "Entry Paid",
	"Clearance": "Field Clearance",
	"Released": "In Delivery",
	"Settled": "Completed",
}


def execute():
	_update_project_shipment_status_options()
	_add_permit_register_on_project()
	_ensure_project_link_on_clearance_doctypes()
	_migrate_shipment_dossiers_to_projects()
	_deactivate_dossier_workflow()
	frappe.clear_cache()
	frappe.db.commit()


def _update_project_shipment_status_options():
	frappe.db.set_value(
		"Custom Field",
		"Project-custom_shipment_status",
		"options",
		NEW_STATUS_OPTIONS,
		update_modified=False,
	)
	ps = frappe.db.get_value(
		"Property Setter",
		{"doc_type": "Project", "field_name": "custom_shipment_status", "property": "options"},
		"name",
	)
	if ps:
		frappe.db.set_value("Property Setter", ps, "value", NEW_STATUS_OPTIONS, update_modified=False)


def _add_permit_register_on_project():
	if frappe.db.exists("Custom Field", "Project-custom_permit_register"):
		return
	cf = frappe.new_doc("Custom Field")
	cf.dt = "Project"
	cf.module = "CGM Worldwide Shipping"
	cf.fieldname = "custom_permit_register"
	cf.fieldtype = "Table"
	cf.label = "Regulatory Permits"
	cf.options = "Permit Register"
	cf.insert_after = "custom_shipment_documents"
	cf.description = "DVS, NBA, VMD, ACA/SCA - applied during clearance (not client CI/PKL)."
	cf.insert(ignore_permissions=True)


def _ensure_project_link_on_clearance_doctypes():
	"""Rename shipment_dossier column to project if still present (post-sync)."""
	for dt in LINKED_DOCTYPES:
		meta = frappe.get_meta(dt, cached=False)
		if meta.has_field("project"):
			continue
		if meta.has_field("shipment_dossier"):
			frappe.db.sql(
				f"ALTER TABLE `tab{dt}` CHANGE COLUMN `shipment_dossier` `project` varchar(140)"
			)


def _migrate_shipment_dossiers_to_projects():
	if not frappe.db.exists("DocType", "Shipment Dossier"):
		return
	for d in frappe.get_all("Shipment Dossier", fields=["name", "project", "client", "client_reference", "status"]):
		project = d.project
		if not project:
			project = _create_project_from_dossier(d.name)
		for dt in LINKED_DOCTYPES:
			if frappe.db.has_column(dt, "shipment_dossier"):
				frappe.db.sql(
					f"UPDATE `tab{dt}` SET project = %s WHERE shipment_dossier = %s",
					(project, d.name),
				)
		if d.status:
			mapped = STATUS_MAP.get(d.status, d.status)
			frappe.db.set_value("Project", project, "custom_shipment_status", mapped, update_modified=False)


def _create_project_from_dossier(dossier_name: str) -> str:
	doc = frappe.get_doc("Shipment Dossier", dossier_name)
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	project = frappe.new_doc("Project")
	project.project_name = doc.client_reference or doc.name
	project.customer = doc.client
	project.company = company
	project.custom_mode_of_transport = "Sea"
	project.custom_client_ref_no = doc.client_reference
	project.custom_bl_number = doc.awb_bl_number
	target_status = STATUS_MAP.get(doc.status, doc.status) or "Draft"
	project.custom_shipment_status = "Draft"
	if doc.get("shipment_documents"):
		for row in doc.shipment_documents:
			project.append("custom_shipment_documents", row.as_dict())
	if doc.get("permits"):
		for row in doc.permits:
			project.append("custom_permit_register", row.as_dict())
	project.insert(ignore_permissions=True)
	if target_status and target_status != "Draft":
		frappe.db.set_value(
			"Project",
			project.name,
			"custom_shipment_status",
			target_status,
			update_modified=False,
		)
	frappe.db.set_value("Shipment Dossier", dossier_name, "project", project.name, update_modified=False)
	return project.name


def _deactivate_dossier_workflow():
	if frappe.db.exists("Workflow", "Shipment Clearance Workflow"):
		frappe.db.set_value("Workflow", "Shipment Clearance Workflow", "is_active", 0)
