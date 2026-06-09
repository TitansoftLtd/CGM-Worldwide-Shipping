"""Align Shipment Dossier status options and map legacy statuses.

The workflow fixtures were removed, so this patch only updates the legacy
Shipment Dossier status field options and remaps old demo statuses.
"""
from __future__ import annotations

import frappe

NEW_STATUSES = (
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
	"Settled",
)


def execute():
	_update_shipment_dossier_status_field()
	_map_legacy_statuses()
	frappe.db.commit()


def _update_shipment_dossier_status_field():
	options = "\n".join(NEW_STATUSES)
	frappe.db.set_value(
		"DocField",
		{"parent": "Shipment Dossier", "fieldname": "status"},
		"options",
		options,
		update_modified=False,
	)
	# Property setter overrides DocField on migrate sync
	ps_name = frappe.db.get_value(
		"Property Setter",
		{"doc_type": "Shipment Dossier", "field_name": "status", "property": "options"},
		"name",
	)
	if ps_name:
		frappe.db.set_value("Property Setter", ps_name, "value", options, update_modified=False)
	else:
		ps = frappe.new_doc("Property Setter")
		ps.doctype_or_field = "DocField"
		ps.doc_type = "Shipment Dossier"
		ps.field_name = "status"
		ps.property = "options"
		ps.value = options
		ps.insert(ignore_permissions=True)


def _map_legacy_statuses():
	"""Map old demo statuses to new sea workflow states."""
	mapping = {
		"IDF Open": "UCR Applied",
		"Taxes Paid": "Entry Paid",
		"Clearance": "Field Clearance",
		"Released": "In Delivery",
	}
	for old, new in mapping.items():
		frappe.db.sql(
			"""
			UPDATE `tabShipment Dossier`
			SET status = %s
			WHERE status = %s
			""",
			(new, old),
		)
