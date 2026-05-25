"""Ensure Project carries full shipment core fields (parity with Shipment Dossier)."""
from __future__ import annotations

import frappe

MODULE = "CGM Worldwide Shipping"

SHIPMENT_TYPE_OPTIONS = (
	"Air Import\nSea FCL\nSea LCL\nRoad Import\nTransit\nExport"
)

CFS_CODE_OPTIONS = "MAT\nCSC\nSIG\nTCC\nKAH\nBFT\nICD\nICD-UG\nFFK\nMCT"


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


def ensure_project_shipment_core_fields() -> None:
	"""Add missing shipment fields on Project for end-to-end clearance visibility."""
	# Align shipment type options with dossier / operations chart.
	if frappe.db.exists("Custom Field", "Project-custom_shipment_type"):
		frappe.db.set_value(
			"Custom Field",
			"Project-custom_shipment_type",
			"options",
			SHIPMENT_TYPE_OPTIONS,
			update_modified=False,
		)

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
			"label": "CFS",
			"fieldtype": "Link",
			"options": "CFS Master",
			"insert_after": "custom_entry_no",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_cfs_code",
			"label": "CFS Code",
			"fieldtype": "Select",
			"options": CFS_CODE_OPTIONS,
			"insert_after": "custom_cfs",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_column_break_transport",
			"fieldtype": "Column Break",
			"insert_after": "custom_cfs_code",
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
			"description": "CI, PKL, BL, COC, KRA PIN — synced from Lead/Opportunity/Customer/Tasks.",
		},
	)
	# Shipment documents table (may already exist from ensure_project_shipment_documents_field).
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
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
			"description": "DVS, NBA, VMD, ACA — not client CI/PKL.",
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
