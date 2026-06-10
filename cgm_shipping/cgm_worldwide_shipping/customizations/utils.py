"""Generic DocType metadata helpers — no business logic."""

from __future__ import annotations

import frappe


@frappe.request_cache
def get_field_from_meta(doctype: str, keyword: str) -> str | None:
	"""Return first fieldname containing keyword."""
	meta = frappe.get_meta(doctype)
	for field in meta.fields:
		if keyword in field.fieldname:
			return field.fieldname
	return None


@frappe.request_cache
def get_link_field_for_doctype(doctype: str, target_doctype: str) -> str | None:
	"""Return Link field pointing to target_doctype."""
	meta = frappe.get_meta(doctype)
	for field in meta.fields:
		if field.fieldtype == "Link" and field.options == target_doctype:
			return field.fieldname
	return None


@frappe.request_cache
def get_container_table_field_for_doctype(doctype: str) -> str | None:
	"""Return first child table containing a container_number field."""
	meta = frappe.get_meta(doctype)
	for field in meta.fields:
		if field.fieldtype != "Table":
			continue
		child_meta = frappe.get_meta(field.options)
		if child_meta.has_field("container_number"):
			return field.fieldname
	return None


@frappe.request_cache
def get_quantity_field_after(doctype: str, anchor_field: str) -> str | None:
	"""Return first numeric/data field after anchor field."""
	fields = frappe.get_meta(doctype).fields
	try:
		start = next(i for i, f in enumerate(fields) if f.fieldname == anchor_field)
	except StopIteration:
		return None
	for field in fields[start + 1 :]:
		if field.fieldtype in ("Section Break", "Tab Break", "Table"):
			break
		if field.fieldtype in ("Data", "Float", "Int"):
			return field.fieldname
	return None
