"""Task permits table + document types for completion validation."""
import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_shipment_fields import (
		_create_cf,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules import (
		ensure_task_document_types,
	)

	_create_cf(
		"Task",
		{
			"fieldname": "custom_section_task_permits",
			"label": "Task Permits",
			"fieldtype": "Section Break",
			"insert_after": "custom_task_documents",
			"depends_on": "eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E' && [5,15].includes(doc.custom_sequence_no)",
			"collapsible": 1,
			"description": "Regulatory permits for this step. Invoices attach here; status syncs to Project → Regulatory Permits.",
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_task_permits",
			"label": "Permits (this task)",
			"fieldtype": "Table",
			"options": "Permit Register",
			"insert_after": "custom_section_task_permits",
			"depends_on": "eval:doc.custom_task_flow_key=='SEA_IMPORT_E2E' && [5,15].includes(doc.custom_sequence_no)",
		},
	)
	_create_cf(
		"Permit Register",
		{
			"fieldname": "custom_source_task",
			"label": "Source Task",
			"fieldtype": "Link",
			"options": "Task",
			"insert_after": "permit_type",
			"read_only": 1,
		},
	)

	ensure_task_document_types()
	frappe.clear_cache()
