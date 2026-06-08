"""Align sea workflow states, finance fields on UCR/permits, and permit type ACA/SCA."""
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

WORKFLOW_STATE_STYLES = {
	"Draft": "Primary",
	"Documents Received": "Warning",
	"UCR Applied": "Primary",
	"UCR Paid": "Success",
	"Pre-clearance": "Primary",
	"Client Inspection": "Info",
	"In Transit": "Info",
	"Final Docs Received": "Warning",
	"Manifest Requested": "Warning",
	"Entry Lodged": "Warning",
	"Line Paid & DO Lodged": "Success",
	"Entry Paid": "Success",
	"Post-clearance": "Primary",
	"Field Clearance": "Warning",
	"KPA Paid": "Success",
	"In Delivery": "Info",
	"Containers Returned": "Success",
	"Settled": "Success",
}


def execute():
	_ensure_workflow_states()
	_update_shipment_dossier_status_field()
	_map_legacy_statuses()
	frappe.db.commit()


def _ensure_workflow_states():
	for state, style in WORKFLOW_STATE_STYLES.items():
		if frappe.db.exists("Workflow State", state):
			continue
		doc = frappe.new_doc("Workflow State")
		doc.workflow_state_name = state
		doc.style = style
		doc.insert(ignore_permissions=True)


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
