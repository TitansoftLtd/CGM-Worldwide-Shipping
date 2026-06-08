"""Bill of Lading submit flow: BL Document Type, hidden linked Opportunity field."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_shipment_fields import (
	_create_cf,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	ensure_document_types,
	get_document_type_link_name,
)

BL_DOCUMENT_TYPE_DEFAULTS = {
	"category": "Transport",
	"default_required": 0,
	"required_stage": "Pre-IDF",
}


def execute():
	_ensure_bl_document_type()
	ensure_document_types()

	_create_cf(
		"Bill of Lading",
		{
			"fieldname": "custom_linked_opportunity",
			"label": "Linked Opportunity",
			"fieldtype": "Link",
			"options": "Opportunity",
			"insert_after": "client_ref",
			"hidden": 1,
		},
	)

	cf_name = "Bill of Lading-custom_linked_opportunity"
	if frappe.db.exists("Custom Field", cf_name):
		frappe.db.set_value("Custom Field", cf_name, "hidden", 1)


def _ensure_bl_document_type():
	if get_document_type_link_name("BL"):
		return

	doc = frappe.new_doc("Document Type")
	doc.code = "BL"
	for key, value in BL_DOCUMENT_TYPE_DEFAULTS.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)
	if doc.meta.is_submittable and doc.docstatus == 0:
		doc.submit()
