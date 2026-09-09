# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_upload_metadata import (
	SHIPMENT_DOCUMENT_ATTACHMENTS,
	stamp_child_table_attachment_metadata,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow import (
	stamp_child_table_approval_workflows,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
	normalize_shipment_document_row,
)


class ShipmentDocument(Document):
	pass


def stamp_shipment_document_upload_metadata(doc, fieldname: str) -> None:
	"""Set upload audit fields and sync attachment approval workflow on a parent save."""
	if not doc.meta.has_field(fieldname):
		return

	stamp_child_table_attachment_metadata(doc, fieldname, SHIPMENT_DOCUMENT_ATTACHMENTS)

	for row in doc.get(fieldname) or []:
		normalize_shipment_document_row(row)

	stamp_child_table_approval_workflows(doc, fieldname)
