# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.customizations.attachment_upload_metadata import (
	PERMIT_REGISTER_ATTACHMENTS,
	stamp_child_table_attachment_metadata,
)


class PermitRegister(Document):
	pass


def stamp_permit_register_upload_metadata(doc, fieldname: str) -> None:
	"""Set upload audit fields when permit attachments change on a parent save."""
	stamp_child_table_attachment_metadata(doc, fieldname, PERMIT_REGISTER_ATTACHMENTS)
