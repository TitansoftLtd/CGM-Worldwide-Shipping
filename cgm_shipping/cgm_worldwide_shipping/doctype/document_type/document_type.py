# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class DocumentType(Document):
	def autoname(self):
		# Name by the document Code (naming_rule: "By script").
		if not self.code:
			frappe.throw(frappe._("Code is required"))
		self.name = self.code.strip()

	def after_rename(self, old_name, new_name, merge=False):
		"""Carry the rename into the comma-separated required-document stamps.

		Frappe rewrites Link fields on rename, but Required Document Types is a
		Data field holding several names (CGM Task Template Item is a child table,
		so it cannot hold a Table MultiSelect). Left alone, those references stop
		matching and quietly stop gating task completion.
		"""
		for doctype, fieldname in (
			("CGM Task Template Item", "required_document_types"),
			("Task", "custom_required_document_types"),
		):
			if frappe.db.has_column(doctype, fieldname):
				_rename_token_in_stamp(doctype, fieldname, old_name, new_name)


def _rename_token_in_stamp(doctype: str, fieldname: str, old_name: str, new_name: str) -> None:
	"""Replace one Document Type name inside every comma-separated stamp."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
		parse_required_document_types,
		serialize_required_document_types,
	)

	rows = frappe.get_all(
		doctype,
		filters={fieldname: ["like", f"%{old_name}%"]},
		fields=["name", fieldname],
	)
	for row in rows:
		tokens = parse_required_document_types(row.get(fieldname))
		# LIKE also matches a longer name that contains this one, e.g. COC in COC_EXTRA.
		if old_name not in tokens:
			continue
		updated = [new_name if token == old_name else token for token in tokens]
		frappe.db.set_value(
			doctype,
			row["name"],
			fieldname,
			serialize_required_document_types(updated),
			update_modified=False,
		)
