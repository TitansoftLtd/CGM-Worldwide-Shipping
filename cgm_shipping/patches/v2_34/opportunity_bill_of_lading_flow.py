"""Hide linked-opportunity field on Bill of Lading; ensure BL document type exists."""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import ensure_document_types


def execute():
	ensure_document_types()

	fieldname = "Bill of Lading-custom_linked_opportunity"
	if frappe.db.exists("Custom Field", fieldname):
		frappe.db.set_value("Custom Field", fieldname, "hidden", 1)
