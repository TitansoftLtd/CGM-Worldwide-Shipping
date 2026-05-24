# Copyright (c) 2026, Titansoft Limited and contributors
"""Backward-compatible migration for shipment documents child table field."""

import frappe


def _column_exists(table_name: str, column_name: str) -> bool:
	return bool(frappe.db.sql(f"SHOW COLUMNS FROM `{table_name}` LIKE %s", (column_name,)))


def execute():
	"""Rename legacy `custom_shipment_document` to `custom_shipment_documents` when needed."""
	if not frappe.db.table_exists("Project"):
		return

	meta = frappe.get_meta("Project")
	has_new = meta.has_field("custom_shipment_documents")
	has_old = meta.has_field("custom_shipment_document")

	# Case 1: already on the new fieldname.
	if has_new and not has_old:
		return

	# Case 1b: neither field in meta — create the plural table field.
	if not has_new and not has_old:
		from cgm_shipping.cgm_worldwide_shipping.customizations.utils import ensure_project_shipment_documents_field

		ensure_project_shipment_documents_field()
		return

	# Case 2: old column exists but new doesn't: rename physical column.
	if _column_exists("tabProject", "custom_shipment_document") and not _column_exists(
		"tabProject", "custom_shipment_documents"
	):
		frappe.db.sql(
			"ALTER TABLE `tabProject` CHANGE COLUMN `custom_shipment_document` `custom_shipment_documents` LONGTEXT"
		)

	# Case 3: update Custom Field row (if present) to the plural fieldname.
	old_cf_name = "Project-custom_shipment_document"
	new_cf_name = "Project-custom_shipment_documents"
	if frappe.db.exists("Custom Field", old_cf_name) and not frappe.db.exists("Custom Field", new_cf_name):
		cf = frappe.get_doc("Custom Field", old_cf_name)
		cf.fieldname = "custom_shipment_documents"
		cf.label = "Shipment Documents"
		cf.save(ignore_permissions=True)
		# Use model rename_doc: frappe.rename_doc() public API does not accept ignore_permissions (e.g. cloud / newer Frappe).
		from frappe.model.rename_doc import rename_doc as rename_document

		rename_document(
			doctype="Custom Field",
			old=old_cf_name,
			new=new_cf_name,
			force=True,
			ignore_permissions=True,
			show_alert=False,
		)

	# Keep field-order strings and similar property values in sync.
	for row in frappe.get_all(
		"Property Setter",
		filters={"doc_type": "Project", "value": ["like", "%custom_shipment_document%"]},
		fields=["name", "value"],
	):
		updated = (row.value or "").replace("custom_shipment_document", "custom_shipment_documents")
		if updated != row.value:
			frappe.db.set_value("Property Setter", row.name, "value", updated, update_modified=False)

	frappe.clear_cache(doctype="Project")
