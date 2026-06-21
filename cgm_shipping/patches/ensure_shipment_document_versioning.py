"""Add initial/final document versioning fields to Shipment Document child table."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
	ensure_shipment_document_version_fields,
	migrate_legacy_shipment_document_attachments,
)


def execute():
	if not frappe.db.exists("DocType", "Shipment Document"):
		return
	ensure_shipment_document_version_fields()
	migrate_legacy_shipment_document_attachments()
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		hide_computed_shipment_document_columns,
	)

	hide_computed_shipment_document_columns()
	frappe.db.commit()
