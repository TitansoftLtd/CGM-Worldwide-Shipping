"""Flags for permit invoice handoff to Finance."""
import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_shipment_fields import (
	_create_cf,
)


def execute():
	_create_cf(
		"Task",
		{
			"fieldname": "custom_permit_invoices_submitted",
			"label": "Permit Invoices Submitted to Finance",
			"fieldtype": "Check",
			"insert_after": "custom_sequence_no",
			"read_only": 1,
			"default": "0",
		},
	)
	frappe.clear_cache(doctype="Task")
