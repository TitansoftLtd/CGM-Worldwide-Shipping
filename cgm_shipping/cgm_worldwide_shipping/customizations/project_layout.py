"""Project custom fields and form layout (consolidated).

Idempotent installers called from migrate patches; primary field definitions live in
custom/project.json. Merged from the former project_shipment_fields /
project_container_tracking / project_tracking_layout modules.
"""
from __future__ import annotations

import json

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
	derive_workflow_progress_from_tasks,
	get_all_sea_tasks_for_project,
	get_open_sea_tasks,
	get_tracking_workflow_states,
	sea_task_count,
)


MODULE = "CGM Worldwide Shipping"

SUPPLIER_CONTAINER_CHARGE_FIELDS = (
	"custom_demurrage_free_days",
	"custom_demurrage_daily_rate",
	"custom_detention_free_days",
	"custom_detention_daily_rate",
	"custom_section_shipping_line_rules",
	"custom_shipping_line_free_days_rules",
	"custom_shipping_line_demurrage_tiers",
	"custom_shipping_line_detention_tiers",
)


def _create_cf(dt: str, values: dict) -> None:
	name = f"{dt}-{values['fieldname']}"
	if frappe.db.exists("Custom Field", name):
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	doc.module = MODULE
	for key, value in values.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)


def _upsert_cf(dt: str, values: dict) -> None:
	"""Create or update a Custom Field (keeps Supplier child tables in sync on migrate)."""
	name = f"{dt}-{values['fieldname']}"
	if frappe.db.exists("Custom Field", name):
		doc = frappe.get_doc("Custom Field", name)
		for key, value in values.items():
			setattr(doc, key, value)
		doc.save(ignore_permissions=True)
		return
	_create_cf(dt, values)


def ensure_project_shipment_core_fields() -> None:
	"""Add missing shipment fields on Project for end-to-end clearance visibility."""
	# Shipment type options are maintained on the Custom Field (custom/project.json), not in code.
	_create_cf(
		"Project",
		{
			"fieldname": "custom_consignee",
			"label": "Consignee",
			"fieldtype": "Data",
			"insert_after": "customer",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_section_transport",
			"label": "Transport & Customs",
			"fieldtype": "Section Break",
			"insert_after": "custom_shipment_status",
			"collapsible": 0,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_entry_no",
			"label": "Customs Entry No",
			"fieldtype": "Data",
			"insert_after": "custom_section_transport",
			"in_list_view": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_cfs",
			"label": "Clearance Station",
			"fieldtype": "Link",
			"options": "Clearance Station",
			"insert_after": "custom_entry_no",
		},
	)
	if frappe.db.exists("Custom Field", "Project-custom_cfs"):
		frappe.db.set_value(
			"Custom Field",
			"Project-custom_cfs",
			{"label": "Clearance Station", "options": "Clearance Station"},
			update_modified=False,
		)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_column_break_transport",
			"fieldtype": "Column Break",
			"insert_after": "custom_cfs",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_weight_nw",
			"label": "Weight (NW) KG",
			"fieldtype": "Float",
			"insert_after": "custom_column_break_transport",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_weight_gw",
			"label": "Weight (GW) KG",
			"fieldtype": "Float",
			"insert_after": "custom_weight_nw",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_ata",
			"label": "Actual Time of Arrival (ATA)",
			"fieldtype": "Date",
			"insert_after": "custom_eta",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_vessel_flight",
			"label": "Vessel / Flight",
			"fieldtype": "Data",
			"insert_after": "custom_ata",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_shipping_line",
			"label": "Shipping Line",
			"fieldtype": "Link",
			"options": "Supplier",
			"insert_after": "custom_vessel_flight",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_section_operations",
			"label": "Operations & Charges",
			"fieldtype": "Section Break",
			"insert_after": "custom_shipping_line",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_agent_allocated",
			"label": "Agent Allocated",
			"fieldtype": "Link",
			"options": "Employee",
			"insert_after": "custom_section_operations",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_date_settled",
			"label": "Date Settled",
			"fieldtype": "Date",
			"insert_after": "custom_agent_allocated",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_column_break_charges",
			"fieldtype": "Column Break",
			"insert_after": "custom_date_settled",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_handling_charges",
			"label": "Handling Charges",
			"fieldtype": "Currency",
			"insert_after": "custom_column_break_charges",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_breakbulk_charges",
			"label": "Breakbulk Charges",
			"fieldtype": "Currency",
			"insert_after": "custom_handling_charges",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_kebs_charges",
			"label": "KEBS Charges",
			"fieldtype": "Currency",
			"insert_after": "custom_breakbulk_charges",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_charge_notes",
			"label": "Charge Notes",
			"fieldtype": "Small Text",
			"insert_after": "custom_kebs_charges",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_shipment_description",
			"label": "Cargo Description",
			"fieldtype": "Small Text",
			"insert_after": "custom_charge_notes",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_shipment_remarks",
			"label": "Shipment Remarks",
			"fieldtype": "Text",
			"insert_after": "custom_shipment_description",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_section_client_documents",
			"label": "Client Documents",
			"fieldtype": "Section Break",
			"insert_after": "custom_shipment_remarks",
			"description": "CI, PKL, BL, COC, KRA PIN - synced from Lead/Opportunity/Customer/Tasks.",
		},
	)
	# Shipment documents table (may already exist from ensure_project_documents_field).
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		ensure_project_shipment_documents_field,
	)

	ensure_project_shipment_documents_field()
	if frappe.db.exists("Custom Field", "Project-custom_shipment_documents"):
		frappe.db.set_value(
			"Custom Field",
			"Project-custom_shipment_documents",
			{"insert_after": "custom_section_client_documents", "label": "Client Documents"},
			update_modified=False,
		)

	_create_cf(
		"Project",
		{
			"fieldname": "custom_section_regulatory_permits",
			"label": "Regulatory Permits",
			"fieldtype": "Section Break",
			"insert_after": "custom_shipment_documents",
			"description": "DVS, NBA, VMD, ACA - not client CI/PKL.",
		},
	)
	if not frappe.db.exists("Custom Field", "Project-custom_permit_register"):
		_create_cf(
			"Project",
			{
				"fieldname": "custom_permit_register",
				"label": "Regulatory Permits",
				"fieldtype": "Table",
				"options": "Permit Register",
				"insert_after": "custom_section_regulatory_permits",
			},
		)
	else:
		frappe.db.set_value(
			"Custom Field",
			"Project-custom_permit_register",
			"insert_after",
			"custom_section_regulatory_permits",
			update_modified=False,
		)

	frappe.clear_cache(doctype="Project")


BERTH_PHASE_OPTIONS = "Before Vessel Berth\nAfter Vessel Berthed\nCompleted"


def _set_cf_property(fieldname: str, **kwargs) -> None:
	name = f"Project-{fieldname}"
	if not frappe.db.exists("Custom Field", name):
		return
	for key, value in kwargs.items():
		frappe.db.set_value("Custom Field", name, key, value, update_modified=False)


def ensure_supplier_field_order() -> None:
	"""Ensure CGM Supplier fields are listed in field_order (otherwise they stay hidden)."""
	ps_name = "Supplier-main-field_order"
	if not frappe.db.exists("Property Setter", ps_name):
		return
	raw = frappe.db.get_value("Property Setter", ps_name, "value") or "[]"
	try:
		order = json.loads(raw)
	except json.JSONDecodeError:
		return
	if not isinstance(order, list):
		return

	order = [f for f in order if f not in SUPPLIER_CONTAINER_CHARGE_FIELDS]
	anchor = "image" if "image" in order else "supplier_group"
	if anchor in order:
		idx = order.index(anchor) + 1
		for offset, fieldname in enumerate(SUPPLIER_CONTAINER_CHARGE_FIELDS):
			order.insert(idx + offset, fieldname)
	else:
		order.extend(SUPPLIER_CONTAINER_CHARGE_FIELDS)

	frappe.db.set_value(
		"Property Setter", ps_name, "value", json.dumps(order), update_modified=False
	)


def ensure_supplier_container_charge_fields() -> None:
	"""Per shipping line: legacy flat fields (fallback) and tiered rule child tables."""
	insert_after = "image"
	for fieldname, label in (
		("custom_demurrage_free_days", "Demurrage Free Days (legacy)"),
		("custom_demurrage_daily_rate", "Demurrage Daily Rate (legacy USD)"),
		("custom_detention_free_days", "Detention Free Days (legacy)"),
		("custom_detention_daily_rate", "Detention Daily Rate (legacy USD)"),
	):
		_upsert_cf(
			"Supplier",
			{
				"fieldname": fieldname,
				"label": label,
				"fieldtype": "Int" if "days" in fieldname else "Currency",
				"insert_after": insert_after,
			},
		)
		insert_after = fieldname
	_upsert_cf(
		"Supplier",
		{
			"fieldname": "custom_section_shipping_line_rules",
			"label": "Container charge rules",
			"fieldtype": "Section Break",
			"insert_after": "custom_detention_daily_rate",
			"collapsible": 1,
		},
	)
	insert_after = "custom_section_shipping_line_rules"
	for fieldname, label, options in (
		(
			"custom_shipping_line_free_days_rules",
			"Shipping Line Free Days Rules",
			"Shipping Line Free Days Rule",
		),
		(
			"custom_shipping_line_demurrage_tiers",
			"Shipping Line Demurrage Tiers",
			"Shipping Line Demurrage Tier",
		),
		(
			"custom_shipping_line_detention_tiers",
			"Shipping Line Detention Tiers",
			"Shipping Line Detention Tier",
		),
	):
		_upsert_cf(
			"Supplier",
			{
				"fieldname": fieldname,
				"label": label,
				"fieldtype": "Table",
				"options": options,
				"insert_after": insert_after,
			},
		)
		insert_after = fieldname
	ensure_supplier_field_order()
	frappe.clear_cache(doctype="Supplier")


def ensure_container_tracking_settings_fields() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CONTAINER_TASK_SEQ_DEFAULTS,
	)

	_create_cf(
		"CGM Shipping Settings",
		{
			"fieldname": "section_container_task_sequences",
			"label": "Container tracking tasks",
			"fieldtype": "Section Break",
			"insert_after": "custom_ucr_finance_email_template",
			"description": "Sea task sequence numbers that update Container Tracker records.",
		},
	)
	insert_after = "section_container_task_sequences"
	for fieldname, default in CONTAINER_TASK_SEQ_DEFAULTS.items():
		label = fieldname.replace("custom_", "").replace("_task_seq", "").replace("_", " ").title()
		_create_cf(
			"CGM Shipping Settings",
			{
				"fieldname": fieldname,
				"label": label,
				"fieldtype": "Int",
				"default": str(default),
				"insert_after": insert_after,
			},
		)
		insert_after = fieldname
	_create_cf(
		"CGM Shipping Settings",
		{
			"fieldname": "custom_kpa_free_days",
			"label": "Default KPA Free Days",
			"fieldtype": "Int",
			"default": "5",
			"insert_after": insert_after,
			"description": "Default KPA free days applied to new Container Tracker records.",
		},
	)
	frappe.clear_cache(doctype="CGM Shipping Settings")


def ensure_task_container_fields() -> None:
	"""Task fields to identify one container for container-specific lifecycle events."""
	_create_cf(
		"Task",
		{
			"fieldname": "custom_section_container_event",
			"label": "Container Event",
			"fieldtype": "Section Break",
			"insert_after": "custom_sequence_no",
			"collapsible": 1,
			"depends_on": (
				"eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E' && "
				"[20,21,22,23,24].includes(doc.custom_sequence_no)"
			),
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_container_tracker",
			"label": "Container Tracker",
			"fieldtype": "Link",
			"options": "Container Tracker",
			"insert_after": "custom_section_container_event",
			"depends_on": (
				"eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E' && "
				"[20,21,22,23,24].includes(doc.custom_sequence_no)"
			),
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_container_number",
			"label": "Container Number",
			"fieldtype": "Data",
			"insert_after": "custom_container_tracker",
			"depends_on": (
				"eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E' && "
				"[20,21,22,23,24].includes(doc.custom_sequence_no)"
			),
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_type_of_container",
			"label": "Type of Container",
			"fieldtype": "Link",
			"options": "Container Type",
			"insert_after": "custom_container_number",
			"depends_on": (
				"eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E' && "
				"[20,21,22,23,24].includes(doc.custom_sequence_no)"
			),
		},
	)
	frappe.clear_cache(doctype="Task")


def ensure_task_container_update_fields() -> None:
	"""Task child table for per-container data entry (tasks 11, 16, 18–24)."""
	container_seqs = "11,16,18,19,20,21,22,23,24"
	depends = (
		f"eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E' && "
		f"[{container_seqs}].includes(doc.custom_sequence_no)"
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_section_container_updates",
			"label": "Container Updates",
			"fieldtype": "Section Break",
			"insert_after": "custom_sequence_no",
			"collapsible": 1,
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_container_updates",
			"label": "Container Updates",
			"fieldtype": "Table",
			"options": "Task Container Update",
			"insert_after": "custom_section_container_updates",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_not_emptied_reason",
			"label": "If containers not exiting port — reason",
			"fieldtype": "Small Text",
			"insert_after": "custom_container_updates",
			"depends_on": (
				"eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E' && "
				"doc.custom_sequence_no == 19"
			),
			"description": (
				"Required when task is completed but no truck details are filled "
				"for any container."
			),
		},
	)
	frappe.clear_cache(doctype="Task")


def ensure_project_container_tracking_fields() -> None:
	ensure_supplier_container_charge_fields()
	ensure_container_tracking_settings_fields()
	_create_cf(
		"Project",
		{
			"fieldname": "custom_section_before_berth",
			"label": "Before Vessel Berth (Mombasa CNT)",
			"fieldtype": "Section Break",
			"insert_after": "custom_port_cfs_charges_note",
			"collapsible": 1,
			"description": "Pre-arrival updates - fill before the vessel berths. Do not use ATA here until the ship arrives.",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_berth_phase",
			"label": "Berth Phase",
			"fieldtype": "Select",
			"options": BERTH_PHASE_OPTIONS,
			"insert_after": "custom_section_before_berth",
			"default": "Before Vessel Berth",
			"read_only": 0,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_batch_no",
			"label": "Batch No",
			"fieldtype": "Data",
			"insert_after": "custom_berth_phase",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_shipment_quantity",
			"label": "Quantity",
			"fieldtype": "Float",
			"insert_after": "custom_batch_no",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_do_reference",
			"label": "Delivery Order (D.O)",
			"fieldtype": "Data",
			"insert_after": "custom_shipment_quantity",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_column_break_before_berth",
			"fieldtype": "Column Break",
			"insert_after": "custom_do_reference",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_custom_release_date",
			"label": "Custom Release Date",
			"fieldtype": "Date",
			"insert_after": "custom_column_break_before_berth",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_entry_taxes_note",
			"label": "Entry & Taxes",
			"fieldtype": "Small Text",
			"insert_after": "custom_custom_release_date",
			"description": "Entry duties/taxes narrative - use Entry No field for the official number.",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_section_container_tracking",
			"label": "Container Tracking (After Vessel Berth)",
			"fieldtype": "Section Break",
			"insert_after": "custom_entry_taxes_note",
			"collapsible": 1,
			"description": "One Container Tracker row per unit. Demurrage, detention, and empty return are calculated per container.",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_container_tracking_html",
			"label": "Containers",
			"fieldtype": "HTML",
			"insert_after": "custom_section_container_tracking",
			"read_only": 1,
		},
	)

	# Reorder: before-berth block after port charges, container section before operations close-out
	chain = (
		("custom_section_before_berth", "custom_port_cfs_charges_note"),
		("custom_berth_phase", "custom_section_before_berth"),
		("custom_batch_no", "custom_berth_phase"),
		("custom_shipment_quantity", "custom_batch_no"),
		("custom_do_reference", "custom_shipment_quantity"),
		("custom_column_break_before_berth", "custom_do_reference"),
		("custom_custom_release_date", "custom_column_break_before_berth"),
		("custom_entry_taxes_note", "custom_custom_release_date"),
		("custom_section_container_tracking", "custom_entry_taxes_note"),
		("custom_container_tracking_html", "custom_section_container_tracking"),
		("custom_section_operations", "custom_container_tracking_html"),
	)
	for fieldname, insert_after in chain:
		_set_cf_property(fieldname, insert_after=insert_after)

	frappe.clear_cache(doctype="Project")


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
			"description": "e.g. CGM/LCL001/1022 - can match Project Name",
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
			"fieldname": "custom_client_ref_no",
			"label": "Client Ref No",
			"fieldtype": "Data",
			"insert_after": "custom_mode_of_transport",
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
			"description": "Free text e.g. GW 437 KGS / NW 760KG - use NW/GW fields when numeric",
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
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
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
	states = get_tracking_workflow_states()
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
	total = len(tasks) or sea_task_count()

	progress_status, progress_index = derive_workflow_progress_from_tasks(tasks, states)
	visible_tasks = (
		get_all_sea_tasks_for_project(project) if doc.get("custom_mode_of_transport") == "Sea" else []
	)
	open_tasks = get_open_sea_tasks(project) if doc.get("custom_mode_of_transport") == "Sea" else []
	first_open = open_tasks[0] if open_tasks else None
	workflow_behind = workflow_index < progress_index
	if workflow_behind and doc.get("custom_mode_of_transport") == "Sea":
		from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
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

	from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
		get_containers_for_project,
	)

	containers = get_containers_for_project(project)

	berth_phase = doc.get("custom_berth_phase") or "Before Vessel Berth"
	if doc.get("custom_ata") or any(
		c.get("discharging_date") or c.get("discharge_date") for c in containers
	):
		berth_phase = "After Vessel Berthed"

	def _count_status(*statuses):
		return sum(1 for c in containers if c.get("status") in statuses)

	alert_count = sum(1 for c in containers if c.get("alert_status"))
	released = _count_status("Released / In Transit")
	at_warehouse = _count_status("At Warehouse", "Cargo Offloaded")
	returned = _count_status("Empty Returned", "Interchange Received")

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
		"cgm_ref_no": doc.get("custom_cgm_ref_no") or doc.name,
		"containers": containers,
		"container_total": len(containers),
		"containers_released": released,
		"containers_at_warehouse": at_warehouse,
		"containers_returned": returned,
		"containers_alerts": alert_count,
		"containers_overdue": sum(
			1
			for c in containers
			if c.get("status") == "Return Overdue"
			or (c.get("alert_status") or "").startswith("🚨")
		),
		"containers_pending_empty": sum(
			1
			for c in containers
			if c.get("status")
			in (
				"Released / In Transit",
				"At Warehouse",
				"Cargo Offloaded",
				"Return Overdue",
			)
		),
		"total_demurrage_amount": sum(c.get("demurrage_amount") or 0 for c in containers),
		"total_detention_amount": sum(c.get("detention_amount") or 0 for c in containers),
	}
