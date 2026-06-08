"""Project layout: before-berth fields + container tracking section."""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_shipment_fields import (
	_create_cf,
)

BERTH_PHASE_OPTIONS = "Before Vessel Berth\nAfter Vessel Berthed\nCompleted"


def _set_cf_property(fieldname: str, **kwargs) -> None:
	name = f"Project-{fieldname}"
	if not frappe.db.exists("Custom Field", name):
		return
	for key, value in kwargs.items():
		frappe.db.set_value("Custom Field", name, key, value, update_modified=False)


def ensure_project_container_tracking_fields() -> None:
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
