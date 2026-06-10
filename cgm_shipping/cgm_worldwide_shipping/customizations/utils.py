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


@frappe.request_cache
def get_bl_config() -> dict:
	"""Fetch Bill of Lading config from Document Type master."""
	dt_meta = frappe.get_meta("Document Type")
	config_fields = [
		name
		for name in (
			"linked_doctype",
			"attachment_field",
			"opportunity_bl_field",
			"opportunity_quantity_field",
			"opportunity_container_field",
			"opportunity_source_field",
		)
		if dt_meta.has_field(name)
	]
	config = {}
	if config_fields and dt_meta.has_field("linked_doctype"):
		config = (
			frappe.db.get_value(
				"Document Type",
				{"linked_doctype": "Bill of Lading"},
				config_fields,
				as_dict=True,
			)
			or {}
		)
	if not config.get("attachment_field"):
		config["attachment_field"] = get_field_from_meta("Bill of Lading", "attach_bill")
	if not config.get("opportunity_bl_field"):
		config["opportunity_bl_field"] = get_link_field_for_doctype("Opportunity", "Bill of Lading")
	if not config.get("opportunity_quantity_field"):
		bl_field = config.get("opportunity_bl_field")
		if bl_field:
			config["opportunity_quantity_field"] = get_quantity_field_after("Opportunity", bl_field)
	if not config.get("opportunity_container_field"):
		config["opportunity_container_field"] = get_container_table_field_for_doctype("Opportunity")
	if not config.get("opportunity_source_field"):
		config["opportunity_source_field"] = get_link_field_for_doctype("Bill of Lading", "Opportunity")
	return config
