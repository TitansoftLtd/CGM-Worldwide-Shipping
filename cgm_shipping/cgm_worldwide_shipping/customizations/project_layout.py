"""Project custom fields and form layout (consolidated).

Idempotent installers called from migrate patches; primary field definitions live in
custom/project.json. Merged from the former project_shipment_fields /
project_container_tracking / project_tracking_layout modules.
"""
from __future__ import annotations

import json

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
	display_ref_from_values,
	get_project_reference,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
	derive_workflow_progress_from_tasks,
	get_tracking_workflow_states,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
	GENERIC_WORKFLOW_STATES,
	derive_generic_workflow_progress,
	get_all_workflow_tasks_for_project,
	get_open_workflow_tasks_for_project,
	get_workflow_tasks_for_project,
	project_has_workflow_tasks,
	project_uses_clearance_workflow_states,
	workflow_task_count_for_project,
)


MODULE = "CGM Worldwide Shipping"

SUPPLIER_CONTAINER_CHARGE_FIELDS = (
	"custom_section_shipping_line_rules",
	"custom_shipping_line_free_days_rules",
	"custom_shipping_line_demurrage_tiers",
)

SUPPLIER_LEGACY_CHARGE_FIELDS = (
	"custom_demurrage_free_days",
	"custom_demurrage_daily_rate",
	"custom_detention_free_days",
	"custom_detention_daily_rate",
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


def _remove_cf(dt: str, fieldname: str) -> None:
	name = f"{dt}-{fieldname}"
	if frappe.db.exists("Custom Field", name):
		frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)


NON_LAYOUT_CF_KEYS = frozenset(
	{
		"fieldname",
		"insert_after",
		"label",
		"fieldtype",
		"options",
		"collapsible",
		"bold",
		"columns",
		"width",
	}
)


def _ensure_cf(dt: str, values: dict) -> None:
	"""Create a custom field if missing; never overwrite layout on existing fields.

	Desk exports (custom/*.json) and Customize Form are the source of truth for
	field order, labels, and insert_after. Migrate only creates missing fields and
	applies non-layout behaviour (read_only, cannot_add_rows, etc.).
	"""
	name = f"{dt}-{values['fieldname']}"
	if not frappe.db.exists("Custom Field", name):
		_create_cf(dt, values)
		return

	doc = frappe.get_doc("Custom Field", name)
	changed = False
	for key, value in values.items():
		if key in NON_LAYOUT_CF_KEYS:
			continue
		if doc.get(key) != value:
			doc.set(key, value)
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


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


def check_project_layout_export_drift() -> list[str]:
	"""Return Project custom fields that exist in DB but are missing from field_order.

	When non-empty, export Customize Form to ``custom/project.json`` so production
	migrate applies the same layout (``sync_on_migrate``).
	"""
	ps_name = "Project-main-field_order"
	if not frappe.db.exists("Property Setter", ps_name):
		return []

	raw = frappe.db.get_value("Property Setter", ps_name, "value") or "[]"
	try:
		order = json.loads(raw)
	except json.JSONDecodeError:
		return []

	if not isinstance(order, list):
		return []

	order_set = set(order)
	return sorted(
		fn
		for fn in frappe.get_all("Custom Field", filters={"dt": "Project"}, pluck="fieldname")
		if fn not in order_set
	)


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

	order = [
		f
		for f in order
		if f not in SUPPLIER_CONTAINER_CHARGE_FIELDS
		and f not in SUPPLIER_LEGACY_CHARGE_FIELDS
		and f != "custom_is_shipping_line"
	]

	# Place Is Shipping Line next to Is Transporter.
	if "is_transporter" in order:
		idx = order.index("is_transporter") + 1
		order.insert(idx, "custom_is_shipping_line")
	elif "custom_is_shipping_line" not in order:
		order.append("custom_is_shipping_line")

	anchor = "custom_is_shipping_line" if "custom_is_shipping_line" in order else (
		"image" if "image" in order else "supplier_group"
	)
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
	"""Shipping-line flag + child tables. Legacy fields removed — see custom/supplier.json."""
	for fieldname in SUPPLIER_LEGACY_CHARGE_FIELDS:
		_remove_cf("Supplier", fieldname)
	_upsert_cf(
		"Supplier",
		{
			"fieldname": "custom_is_shipping_line",
			"label": "Is Shipping Line",
			"fieldtype": "Check",
			"insert_after": "is_transporter",
			"description": "When checked, this supplier appears in Shipping Line link fields.",
		},
	)
	_upsert_cf(
		"Supplier",
		{
			"fieldname": "custom_section_shipping_line_rules",
			"label": "Container charge rules",
			"fieldtype": "Section Break",
			"insert_after": "custom_is_shipping_line",
			"collapsible": 1,
			"depends_on": "eval:doc.custom_is_shipping_line",
		},
	)
	insert_after = "custom_section_shipping_line_rules"
	for fieldname, label, options in (
		(
			"custom_shipping_line_free_days_rules",
			"Shipping Line Free Days Rules (optional reference)",
			"Shipping Line Free Days Rule",
		),
		(
			"custom_shipping_line_demurrage_tiers",
			"Shipping Line Demurrage Tiers",
			"Shipping Line Demurrage Tier",
		),
	):
		cf_values = {
			"fieldname": fieldname,
			"label": label,
			"fieldtype": "Table",
			"options": options,
			"insert_after": insert_after,
			"depends_on": "eval:doc.custom_is_shipping_line",
		}
		if fieldname == "custom_shipping_line_free_days_rules":
			cf_values["description"] = (
				"Optional reference only. Container Tracker free-day start/end dates "
				"drive demurrage day counts."
			)
		_upsert_cf("Supplier", cf_values)
		insert_after = fieldname
	ensure_supplier_field_order()
	frappe.clear_cache(doctype="Supplier")


def ensure_container_tracking_settings_fields() -> None:
	"""Container tracking settings live on CGM Shipping Settings doctype JSON.

	Remove legacy Custom Field duplicates from older installs.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CONTAINER_TASK_SEQ_DEFAULTS,
	)

	for fieldname in (
		"section_container_task_sequences",
		*CONTAINER_TASK_SEQ_DEFAULTS.keys(),
		"custom_kpa_free_days",
	):
		_remove_cf("CGM Shipping Settings", fieldname)

	if frappe.db.exists("DocType", "CGM Shipping Settings"):
		kpa = frappe.db.get_single_value("CGM Shipping Settings", "custom_kpa_free_days")
		if kpa in (None, 0):
			frappe.db.set_single_value(
				"CGM Shipping Settings", "custom_kpa_free_days", 5, update_modified=False
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
				"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && "
				"[22,23,24,25,26].includes(doc.custom_sequence_no)"
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
				"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && "
				"[21,22,23,24,25].includes(doc.custom_sequence_no)"
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
				"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && "
				"[21,22,23,24,25].includes(doc.custom_sequence_no)"
			),
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_cargo_type",
			"label": "Cargo Type",
			"fieldtype": "Link",
			"options": "Cargo Type",
			"insert_after": "custom_container_number",
			"depends_on": (
				"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && "
				"[21,22,23,24,25].includes(doc.custom_sequence_no)"
			),
		},
	)
	frappe.clear_cache(doctype="Task")


def ensure_task_container_update_fields() -> None:
	"""Task child table for per-container data entry (SL deposit + transport steps)."""
	# Include Shipping Line application (10) for deposit confirmation.
	container_seqs = "10,12,17,19,20,21,22,23,24,25"
	depends = (
		f"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && "
		f"[{container_seqs}].includes(doc.custom_sequence_no)"
	)
	for fieldname, values in (
		(
			"custom_section_container_updates",
			{
				"fieldname": "custom_section_container_updates",
				"label": "Container Updates",
				"fieldtype": "Section Break",
				"insert_after": "custom_sequence_no",
				"collapsible": 1,
				"depends_on": depends,
			},
		),
		(
			"custom_container_updates",
			{
				"fieldname": "custom_container_updates",
				"label": "Container Updates",
				"fieldtype": "Table",
				"options": "Task Container Update",
				"insert_after": "custom_section_container_updates",
				"depends_on": depends,
			},
		),
	):
		name = f"Task-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			doc = frappe.get_doc("Custom Field", name)
			if doc.depends_on != depends:
				doc.depends_on = depends
				doc.save(ignore_permissions=True)
		else:
			_create_cf("Task", values)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_not_emptied_reason",
			"label": "If containers not exiting port — reason",
			"fieldtype": "Small Text",
			"insert_after": "custom_container_updates",
			"depends_on": (
				"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && "
				"doc.custom_sequence_no == 21"
			),
			"description": (
				"Required when task is completed but no truck details are filled "
				"for any container."
			),
		},
	)
	frappe.clear_cache(doctype="Task")


def ensure_field_officer_task_fields() -> None:
	"""Task 16 field-officer clearance tracking fields."""
	depends = (
		"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && doc.custom_sequence_no == 18"
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_section_field_clearance",
			"label": "Field Clearance",
			"fieldtype": "Section Break",
			"insert_after": "custom_task_documents",
			"collapsible": 1,
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_verification_type",
			"label": "Verification Type",
			"fieldtype": "Select",
			"options": (
				"\nPartial Verification\n100% Verification\nDirect Release\nScanning"
			),
			"insert_after": "custom_section_field_clearance",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_verification_status",
			"label": "Verification Status",
			"fieldtype": "Select",
			"options": (
				"\nNot Started\nIn Progress\nVerification Done\nReleased by CRO"
			),
			"insert_after": "custom_verification_type",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_customs_issue",
			"label": "Customs Issues / Holds",
			"fieldtype": "Small Text",
			"description": "Any holds, queries, or issues from KRA/KEBS",
			"insert_after": "custom_verification_status",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_delivery_note_status",
			"label": "Delivery Note Status",
			"fieldtype": "Select",
			"options": "\nNot Required\nAwaiting\nIssued",
			"insert_after": "custom_customs_issue",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_coc_status",
			"label": "COC Approval Status",
			"fieldtype": "Select",
			"options": "\nNot Required\nAwaiting COC\nCOC Received\nApproved",
			"insert_after": "custom_delivery_note_status",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_verification_report_attached",
			"label": "Verification Report Attached",
			"fieldtype": "Check",
			"insert_after": "custom_coc_status",
			"depends_on": depends,
		},
	)
	frappe.clear_cache(doctype="Task")


def ensure_client_inspection_task_fields() -> None:
	"""Task 7 client inspection notification / confirmation fields."""
	depends = (
		"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && doc.custom_sequence_no == 7"
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_section_client_inspection",
			"label": "Client Inspection",
			"fieldtype": "Section Break",
			"insert_after": "custom_task_documents",
			"collapsible": 1,
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_client_notified_on",
			"label": "Client Notified On",
			"fieldtype": "Datetime",
			"insert_after": "custom_section_client_inspection",
			"read_only": 1,
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_client_notified_by",
			"label": "Client Notified By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "custom_client_notified_on",
			"read_only": 1,
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_inspection_confirmed_on",
			"label": "Inspection Confirmed On",
			"fieldtype": "Datetime",
			"insert_after": "custom_client_notified_by",
			"read_only": 1,
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_inspection_confirmed_by",
			"label": "Inspection Confirmed By",
			"fieldtype": "Data",
			"insert_after": "custom_inspection_confirmed_on",
			"read_only": 1,
			"depends_on": depends,
		},
	)
	frappe.clear_cache(doctype="Task")


def ensure_project_inspection_notification_fields() -> None:
	"""Project-level inspection notification status for portal + desk indicator."""
	_create_cf(
		"Project",
		{
			"fieldname": "custom_inspection_notification_status",
			"label": "Inspection Notification Status",
			"fieldtype": "Select",
			"options": "Not Notified\nNotified\nConfirmed",
			"default": "Not Notified",
			"insert_after": "custom_shipment_status",
			"read_only": 1,
			"hidden": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_inspection_notified_on",
			"label": "Inspection Notified On",
			"fieldtype": "Datetime",
			"insert_after": "custom_inspection_notification_status",
			"read_only": 1,
			"hidden": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_inspection_confirmed_on",
			"label": "Inspection Confirmed On",
			"fieldtype": "Datetime",
			"insert_after": "custom_inspection_notified_on",
			"read_only": 1,
			"hidden": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_inspection_confirmed_by",
			"label": "Inspection Confirmed By",
			"fieldtype": "Data",
			"insert_after": "custom_inspection_confirmed_on",
			"read_only": 1,
			"hidden": 1,
		},
	)
	frappe.clear_cache(doctype="Project")


def ensure_project_port_arrival_fields() -> None:
	"""Early port-arrival confirmation (creates container trackers before Entry is paid)."""
	_create_cf(
		"Project",
		{
			"fieldname": "custom_port_arrival_confirmed",
			"label": "Port Arrival Confirmed",
			"fieldtype": "Check",
			"insert_after": "custom_berth_phase",
			"read_only": 1,
			"default": "0",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_port_arrival_confirmed_on",
			"label": "Port Arrival Confirmed On",
			"fieldtype": "Datetime",
			"insert_after": "custom_port_arrival_confirmed",
			"read_only": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_port_arrival_confirmed_by",
			"label": "Port Arrival Confirmed By",
			"fieldtype": "Data",
			"insert_after": "custom_port_arrival_confirmed_on",
			"read_only": 1,
		},
	)
	frappe.clear_cache(doctype="Project")


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
	"""Fields matching the shipment tracking sheet columns."""
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
			"fieldname": "custom_project_reference",
			"label": "Project Reference",
			"fieldtype": "Data",
			"insert_after": "project_name",
			"in_list_view": 1,
			"in_standard_filter": 1,
			"in_global_search": 1,
			"read_only": 1,
			"description": "Business project reference (e.g. PO-99 / 3X20 / 1 or PO-99 / 10 Cartons).",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_cgm_ref_no",
			"label": "CGM Ref No",
			"fieldtype": "Data",
			"hidden": 1,
			"insert_after": "custom_project_reference",
			"read_only": 1,
			"description": "Legacy CGM reference (superseded by Project Reference).",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_column_break_tracking_1",
			"fieldtype": "Column Break",
			"insert_after": "custom_project_reference",
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
		("custom_project_reference", "custom_consignee"),
		("custom_column_break_tracking_1", "custom_project_reference"),
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
	use_clearance_states = project_uses_clearance_workflow_states(doc)
	states = get_tracking_workflow_states() if use_clearance_states else list(GENERIC_WORKFLOW_STATES)
	try:
		workflow_index = states.index(workflow_status)
	except ValueError:
		workflow_index = 0

	tasks = get_workflow_tasks_for_project(
		doc,
		fields=["custom_sequence_no", "status", "subject", "custom_permit_invoices_submitted"],
		limit=100,
	)
	completed = sum(1 for t in tasks if t.status == "Completed")
	total = len(tasks) or workflow_task_count_for_project(doc)

	if use_clearance_states:
		progress_status, progress_index = derive_workflow_progress_from_tasks(tasks, states)
	else:
		progress_status, progress_index = derive_generic_workflow_progress(tasks)

	visible_tasks = get_all_workflow_tasks_for_project(project) if project_has_workflow_tasks(doc) else []
	open_tasks = get_open_workflow_tasks_for_project(project) if project_has_workflow_tasks(doc) else []
	first_open = open_tasks[0] if open_tasks else None
	workflow_behind = workflow_index < progress_index
	if workflow_behind and use_clearance_states and doc.get("custom_mode_of_transport") == "Sea":
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

	from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
		enrich_containers_with_allocation,
	)

	containers = enrich_containers_with_allocation(containers)

	berth_phase = doc.get("custom_berth_phase") or "Before Vessel Berth"
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import get_project_ata

	if get_project_ata(doc) or any(
		c.get("discharging_date") or c.get("discharge_date") for c in containers
	):
		berth_phase = "After Vessel Berthed"

	def _count_status(*statuses):
		return sum(1 for c in containers if c.get("status") in statuses)

	alert_count = sum(
		1
		for c in containers
		if c.get("alert_status")
		or (c.get("demurrage_days") or 0) > 0
		or (c.get("days_outstanding") or 0) > 0
	)
	released = _count_status("Released / In Transit")
	at_warehouse = _count_status("At Warehouse", "Cargo Offloaded")
	returned = _count_status("Empty Returned", "Interchange Received")

	payload = {
		"current_status": progress_status,
		"current_index": progress_index,
		"workflow_status": workflow_status,
		"workflow_index": workflow_index,
		"workflow_behind": workflow_behind,
		"states": states,
		"tasks_completed": completed,
		"tasks_total": total,
		"workflow_tasks": visible_tasks,
		"sea_tasks": visible_tasks,
		"first_open_task": first_open,
		"mode": doc.get("custom_mode_of_transport"),
		"uses_clearance_states": use_clearance_states,
		"has_workflow_tasks": bool(visible_tasks or tasks),
		"task_progress_label": "clearance tasks" if use_clearance_states else "workflow tasks",
		"berth_phase": berth_phase,
		"project_reference": get_project_reference(doc) or doc.name,
		"cgm_ref_no": get_project_reference(doc) or doc.name,
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
		"containers_in_demurrage": sum(1 for c in containers if (c.get("demurrage_days") or 0) > 0),
		"containers_in_kpa_charges": sum(1 for c in containers if (c.get("kpa_days") or 0) > 0),
		"total_demurrage_days": sum(c.get("demurrage_days") or 0 for c in containers),
		"total_kpa_days": sum(c.get("kpa_days") or 0 for c in containers),
		"total_demurrage_amount": sum(c.get("demurrage_amount") or 0 for c in containers),
		"total_kpa_amount": sum(c.get("kpa_amount") or 0 for c in containers),
		"total_detention_amount": sum(c.get("detention_amount") or 0 for c in containers),
	}
	if doc.meta.has_field("custom_inspection_notification_status"):
		payload["inspection_notification_status"] = (
			doc.get("custom_inspection_notification_status") or "Not Notified"
		).strip()
		payload["inspection_notified_on"] = doc.get("custom_inspection_notified_on")
		payload["inspection_confirmed_on"] = doc.get("custom_inspection_confirmed_on")
		payload["inspection_confirmed_by"] = doc.get("custom_inspection_confirmed_by")
	if doc.meta.has_field("custom_port_arrival_confirmed"):
		payload["port_arrival_confirmed"] = bool(doc.get("custom_port_arrival_confirmed"))
		payload["port_arrival_confirmed_on"] = doc.get("custom_port_arrival_confirmed_on")
		payload["port_arrival_confirmed_by"] = doc.get("custom_port_arrival_confirmed_by")
	return payload


OBSOLETE_FINANCE_COST_PROJECT_FIELDS = (
	"custom_finance_cost_ucr",
	"custom_finance_cost_kebs",
	"custom_finance_cost_dvs",
	"custom_finance_cost_idf",
	"custom_finance_cost_port",
	"custom_finance_cost_transport",
	"custom_finance_cost_other",
	"custom_finance_cost_ledger",
	"custom_finance_cost_payment_count",
	"custom_finance_cost_last_payment_date",
	"custom_column_break_finance_cost_summary",
)


def ensure_project_finance_cost_fields() -> None:
	"""Single billed-total field on Project — create if missing; layout from desk export."""
	for fieldname in OBSOLETE_FINANCE_COST_PROJECT_FIELDS:
		_remove_cf("Project", fieldname)

	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_section_finance_cost_summary",
			"label": "Journal Entry Billing",
			"fieldtype": "Section Break",
			"insert_after": "total_purchase_cost",
			"collapsible": 0,
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_finance_cost_total",
			"label": "Total Billed Amount (via Journal Entry)",
			"fieldtype": "Currency",
			"insert_after": "custom_section_finance_cost_summary",
			"read_only": 1,
			"bold": 1,
		},
	)
	frappe.clear_cache(doctype="Project")


def ensure_cargo_type_fields() -> None:
	"""Select Cargo Type on Project / Opportunity / Quotation (from CARGO_TYPE_OPTIONS)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import CARGO_TYPE_OPTIONS

	options = "\n" + "\n".join(CARGO_TYPE_OPTIONS)
	targets = (
		("Project", "custom_shipment_type"),
		("Opportunity", "custom_shipment_type"),
		("Quotation", "custom_shipment_type"),
	)
	for dt, insert_after in targets:
		if not frappe.db.exists("DocType", dt):
			continue
		_create_cf(
			dt,
			{
				"fieldname": "custom_cargo_type",
				"label": "Cargo Type",
				"fieldtype": "Select",
				"options": options,
				"insert_after": insert_after,
			},
		)
		frappe.clear_cache(doctype=dt)


def ensure_transit_project_fields() -> None:
	"""Project fields for container tracker mode, transit entry, and UBS permit tracking."""
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_container_tracker_mode",
			"label": "Container Tracker Mode",
			"fieldtype": "Link",
			"options": "Container Tracker Mode",
			"insert_after": "custom_shipment_type",
			"fetch_from": "custom_shipment_type.container_tracker_mode",
			"fetch_if_empty": 1,
			"in_standard_filter": 1,
			"description": "Where containers for this shipment are tracked (Mombasa, ICD, Transit, Export). Defaults from Shipment Type.",
		},
	)
	_set_cf_property(
		"custom_container_tracker_mode",
		hidden=0,
		fetch_from="custom_shipment_type.container_tracker_mode",
		fetch_if_empty=1,
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_uses_destination_entry",
			"label": "Uses Destination Entry",
			"fieldtype": "Check",
			"insert_after": "custom_shipment_type",
			"fetch_from": "custom_shipment_type.uses_destination_entry",
			"read_only": 1,
			"hidden": 1,
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_destination_entry_number",
			"label": "Destination Entry Number",
			"fieldtype": "Data",
			"insert_after": "project_type",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_ubs_permit_number",
			"label": "UBS Permit Number",
			"fieldtype": "Data",
			"insert_after": "custom_destination_entry_number",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_ubs_permit_date",
			"label": "UBS Permit Date",
			"fieldtype": "Date",
			"insert_after": "custom_ubs_permit_number",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_destination_entry_confirmed",
			"label": "Destination Entry Confirmed",
			"fieldtype": "Check",
			"insert_after": "custom_ubs_permit_date",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_uganda_release_date",
			"label": "Destination Country Release Date",
			"fieldtype": "Date",
			"insert_after": "custom_destination_entry_confirmed",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_coc_application_date",
			"label": "COC Application Date",
			"fieldtype": "Date",
			"insert_after": "custom_uganda_release_date",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_eac_application_date",
			"label": "EAC Application Date",
			"fieldtype": "Date",
			"insert_after": "custom_coc_application_date",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)

	if frappe.db.exists("Property Setter", "Project-project_type-hidden"):
		frappe.db.set_value("Property Setter", "Project-project_type-hidden", "value", "0")

	_backfill_project_container_tracker_modes()
	frappe.clear_cache(doctype="Project")


def _backfill_project_container_tracker_modes() -> None:
	"""Copy Shipment Type container tracker mode onto projects that are still blank."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
		container_tracking_mode_for_shipment_type,
	)

	if not frappe.db.has_column("Project", "custom_container_tracker_mode"):
		return

	for row in frappe.get_all(
		"Project",
		filters={
			"custom_shipment_type": ["is", "set"],
			"custom_container_tracker_mode": ["in", ("", None)],
		},
		fields=["name", "custom_shipment_type"],
		limit=500,
	):
		mode = container_tracking_mode_for_shipment_type(row.custom_shipment_type)
		if not mode:
			continue
		frappe.db.set_value(
			"Project",
			row.name,
			"custom_container_tracker_mode",
			mode,
			update_modified=False,
		)
		if frappe.db.has_column("Project", "project_type"):
			frappe.db.set_value(
				"Project", row.name, "project_type", mode, update_modified=False
			)


def ensure_opportunity_universal_fields() -> None:
	"""Ensure Project shipping fields that mirror Opportunity intake.

	Opportunity layout / custom fields live in ``custom/opportunity.json``
	(``sync_on_migrate``). Do not create Opportunity Custom Fields here.
	"""
	for item in (
		("custom_shipping_order_ref", "Data", "Shipping Order Reference"),
		("custom_booking_ref", "Data", "Booking Reference"),
		("custom_handling_agent", "Data", "Handling Agent"),
		("custom_booking_confirmation", "Link", "Booking Confirmation", "Booking Confirmation"),
	):
		fieldname, fieldtype, label = item[0], item[1], item[2]
		values = {
			"fieldname": fieldname,
			"label": label,
			"fieldtype": fieldtype,
			"insert_after": "custom_cargo_type"
			if fieldname == "custom_booking_confirmation"
			else "custom_shipping_line",
		}
		if len(item) > 3:
			values["options"] = item[3]
		_ensure_cf("Project", values)

	frappe.clear_cache(doctype="Project")
