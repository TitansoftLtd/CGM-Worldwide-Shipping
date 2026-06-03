"""Project form layout: LCL tracking sheet fields + field order (top of form)."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_shipment_fields import (
	MODULE,
	_create_cf,
)

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
	TRACKING_WORKFLOW_STATES,
	derive_workflow_progress_from_tasks,
	get_all_sea_tasks_for_project,
	get_open_sea_tasks,
)


def _set_cf_property(fieldname: str, **kwargs) -> None:
	name = f"Project-{fieldname}"
	if not frappe.db.exists("Custom Field", name):
		return
	for key, value in kwargs.items():
		frappe.db.set_value("Custom Field", name, key, value, update_modified=False)


def _ensure_tracking_fields() -> None:
	"""Fields matching the LCL Shipment Tracking Sheet columns."""
	_create_cf(
		"Project",
		{
			"fieldname": "custom_section_tracking_sheet",
			"label": "Shipment Tracking Sheet",
			"fieldtype": "Section Break",
			"insert_after": "custom_project_details",
			"collapsible": 0,
			"description": "Core shipment data (same columns as the operations tracking spreadsheet).",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_shipment_progress_html",
			"label": "Clearance Progress",
			"fieldtype": "HTML",
			"insert_after": "custom_section_tracking_sheet",
			"read_only": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_opened_date",
			"label": "Date (Opened)",
			"fieldtype": "Date",
			"insert_after": "custom_shipment_progress_html",
			"default": "Today",
			"in_list_view": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_cgm_ref_no",
			"label": "CGM Ref No",
			"fieldtype": "Data",
			"insert_after": "custom_opened_date",
			"in_list_view": 1,
			"description": "e.g. CGM/LCL001/1022 — can match Project Name",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_column_break_tracking_1",
			"fieldtype": "Column Break",
			"insert_after": "custom_cgm_ref_no",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_idf_number",
			"label": "IDF No",
			"fieldtype": "Data",
			"insert_after": "custom_column_break_tracking_1",
			"in_list_view": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_weight_notes",
			"label": "Weight (as per docs)",
			"fieldtype": "Data",
			"insert_after": "custom_weight_gw",
			"description": "Free text e.g. GW 437 KGS / NW 760KG — use NW/GW fields when numeric",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_shipping_line_charges_note",
			"label": "Shipping Line Charges",
			"fieldtype": "Small Text",
			"insert_after": "custom_shipping_line",
			"description": "e.g. USD 987 PAID BY CLIENT",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_port_cfs_charges_note",
			"label": "Port / CFS Charges",
			"fieldtype": "Small Text",
			"insert_after": "custom_shipping_line_charges_note",
			"description": "e.g. KES 4,840 PAID BY CLIENT / storage notes",
		},
	)

	# CFS code comes from the linked CFS Master record (see custom_cfs_code fetch_from).
	_set_cf_property(
		"custom_cfs_code",
		fieldtype="Data",
		fetch_from="custom_cfs.cfs_code",
		fetch_if_empty=1,
		read_only=1,
	)


def _reorder_tracking_field_chain() -> None:
	"""
	Place initiation + tracking fields at the top in spreadsheet order.
	Uses insert_after on Custom Field records.
	"""
	chain = [
		("custom_section_tracking_sheet", "custom_project_details"),
		("custom_shipment_progress_html", "custom_section_tracking_sheet"),
		("custom_opened_date", "custom_shipment_progress_html"),
		("custom_consignee", "custom_opened_date"),
		("custom_cgm_ref_no", "custom_consignee"),
		("custom_column_break_tracking_1", "custom_cgm_ref_no"),
		("custom_shipment_type", "custom_column_break_tracking_1"),
		("custom_mode_of_transport", "custom_shipment_type"),
		("custom_client_ref_no", "custom_mode_of_transport"),
		("custom_shipment_status", "custom_client_ref_no"),
		("custom_bl_number", "custom_shipment_status"),
		("custom_awb_number", "custom_bl_number"),
		("custom_entry_no", "custom_awb_number"),
		("custom_idf_number", "custom_entry_no"),
		("custom_section_transport", "custom_idf_number"),
		("custom_cfs_code", "custom_section_transport"),
		("custom_cfs", "custom_cfs_code"),
		("custom_weight_nw", "custom_cfs"),
		("custom_weight_gw", "custom_weight_nw"),
		("custom_weight_notes", "custom_weight_gw"),
		("custom_eta", "custom_weight_notes"),
		("custom_ata", "custom_eta"),
		("custom_vessel_flight", "custom_ata"),
		("custom_shipping_line", "custom_vessel_flight"),
		("custom_shipping_line_charges_note", "custom_shipping_line"),
		("custom_port_cfs_charges_note", "custom_shipping_line_charges_note"),
		("custom_section_operations", "custom_port_cfs_charges_note"),
		("custom_agent_allocated", "custom_section_operations"),
		("custom_date_settled", "custom_agent_allocated"),
		("custom_kebs_charges", "custom_column_break_charges"),
		("custom_handling_charges", "custom_kebs_charges"),
		("custom_breakbulk_charges", "custom_handling_charges"),
		("custom_charge_notes", "custom_breakbulk_charges"),
		("custom_shipment_description", "custom_charge_notes"),
		("custom_shipment_remarks", "custom_shipment_description"),
		("custom_section_client_documents", "custom_shipment_remarks"),
	]
	for fieldname, insert_after in chain:
		_set_cf_property(fieldname, insert_after=insert_after)

	# Move legacy route block below tracking (optional visibility).
	for fn, after in (
		("custom_section_break_ri62g", "custom_permit_register"),
		("custom_current_location", "custom_section_break_ri62g"),
	):
		_set_cf_property(fn, insert_after=after)


def ensure_project_tracking_layout() -> None:
	"""Run after core shipment fields exist."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_shipment_fields import (
		ensure_project_shipment_core_fields,
	)

	ensure_project_shipment_core_fields()
	_ensure_tracking_fields()
	_reorder_tracking_field_chain()
	frappe.clear_cache(doctype="Project")


@frappe.whitelist()
def get_project_tracking_dashboard(project: str) -> dict:
	"""Data for the HTML workflow chart on Project."""
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	doc = frappe.get_doc("Project", project)
	workflow_status = doc.get("custom_shipment_status") or "Draft"
	states = TRACKING_WORKFLOW_STATES
	try:
		workflow_index = states.index(workflow_status)
	except ValueError:
		workflow_index = 0

	tasks = []
	if frappe.db.exists("Task", {"project": project}):
		tasks = frappe.get_all(
			"Task",
			filters={"project": project, "custom_task_flow_key": "SEA_IMPORT_E2E"},
			fields=[
				"custom_sequence_no",
				"status",
				"subject",
				"custom_permit_invoices_submitted",
			],
			order_by="custom_sequence_no asc",
			limit=30,
		)
	completed = sum(1 for t in tasks if t.status == "Completed")
	total = len(tasks) or 24

	progress_status, progress_index = derive_workflow_progress_from_tasks(tasks, states)
	visible_tasks = (
		get_all_sea_tasks_for_project(project) if doc.get("custom_mode_of_transport") == "Sea" else []
	)
	open_tasks = get_open_sea_tasks(project) if doc.get("custom_mode_of_transport") == "Sea" else []
	first_open = open_tasks[0] if open_tasks else None
	workflow_behind = workflow_index < progress_index
	if workflow_behind and doc.get("custom_mode_of_transport") == "Sea":
		from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance_flow import (
			sync_project_shipment_status_from_tasks,
		)

		synced = sync_project_shipment_status_from_tasks(project)
		if synced:
			workflow_status = synced
			try:
				workflow_index = states.index(synced)
			except ValueError:
				workflow_index = progress_index
			workflow_behind = False

	containers = []
	if frappe.db.exists("DocType", "Container Tracker"):
		from cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker import (
			get_containers_for_project,
		)

		containers = get_containers_for_project(project)

	berth_phase = doc.get("custom_berth_phase") or "Before Vessel Berth"
	if doc.get("custom_ata") or any(c.get("discharging_date") for c in containers):
		berth_phase = "After Vessel Berthed"

	return {
		"current_status": progress_status,
		"current_index": progress_index,
		"workflow_status": workflow_status,
		"workflow_index": workflow_index,
		"workflow_behind": workflow_behind,
		"states": states,
		"tasks_completed": completed,
		"tasks_total": total,
		"sea_tasks": visible_tasks,
		"first_open_task": first_open,
		"mode": doc.get("custom_mode_of_transport"),
		"berth_phase": berth_phase,
		"containers": containers,
		"containers_overdue": sum(1 for c in containers if c.get("status") == "Overdue"),
		"containers_pending_empty": sum(
			1 for c in containers if c.get("status") in ("Empty Pending", "Overdue", "Dispatched")
		),
		"total_demurrage_amount": sum(c.get("demurrage_amount") or 0 for c in containers),
		"total_detention_amount": sum(c.get("detention_amount") or 0 for c in containers),
	}
