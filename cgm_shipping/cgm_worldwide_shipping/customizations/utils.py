"""Generic DocType metadata helpers — no business logic."""

from __future__ import annotations

import frappe

NUMERIC_FIELDTYPES = ("Float", "Currency", "Percent", "Int")


def coerce_numeric_fields(
	doc,
	fieldnames: list[str] | tuple[str, ...] | None = None,
	*,
	empty_as_zero: bool = False,
) -> None:
	"""Normalize empty / non-numeric values on Float-like fields before SQL write.

	Empty strings against decimal columns raise MySQL 1265 (Data truncated).
	"""
	meta = doc.meta
	names = list(fieldnames) if fieldnames is not None else [
		df.fieldname for df in meta.fields if df.fieldtype in NUMERIC_FIELDTYPES
	]
	for fieldname in names:
		if not meta.has_field(fieldname):
			continue
		value = doc.get(fieldname)
		if value is None:
			continue
		df = meta.get_field(fieldname)
		if value == "" or (isinstance(value, str) and not str(value).strip()):
			# NOT NULL decimal columns need 0; nullable Floats can stay empty.
			use_zero = empty_as_zero or bool(getattr(df, "not_nullable", 0))
			if not use_zero and df and df.default not in (None, ""):
				use_zero = True
			doc.set(fieldname, 0 if use_zero else None)
			continue
		if isinstance(value, (int, float)) and not isinstance(value, bool):
			if df and df.fieldtype == "Int":
				doc.set(fieldname, int(value))
			continue
		try:
			num = float(str(value).replace(",", "").strip())
		except (TypeError, ValueError):
			use_zero = empty_as_zero or bool(getattr(df, "not_nullable", 0))
			doc.set(fieldname, 0 if use_zero else None)
			continue
		doc.set(fieldname, int(num) if df and df.fieldtype == "Int" else num)


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


def get_quantity_field_after(doctype: str, after_field: str) -> str | None:
	"""Return first numeric quantity-like field after a given field in field_order."""
	meta = frappe.get_meta(doctype)
	fieldnames = [df.fieldname for df in meta.fields]
	try:
		start = fieldnames.index(after_field) + 1
	except ValueError:
		start = 0
	for fieldname in fieldnames[start:]:
		df = meta.get_field(fieldname)
		if df.fieldtype in ("Float", "Int", "Data") and "quantity" in fieldname.lower():
			return fieldname
	return None


@frappe.request_cache
def get_bl_config() -> dict:
	"""Bill of Lading field mapping config (cached)."""
	config: dict = {}
	if frappe.db.exists("DocType", "Bill of Lading"):
		config["opportunity_bl_field"] = get_link_field_for_doctype("Opportunity", "Bill of Lading")
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
	config["attachment_field"] = resolve_doctype_attachment_field(
		"Bill of Lading",
		"attach_bill_of_lading",
		"attach_bill",
		"attach_bl",
	)
	return config


def resolve_doctype_attachment_field(doctype: str, *preferred: str) -> str | None:
	"""Return the primary Attach field on a DocType (explicit names first)."""
	if not doctype or not frappe.db.exists("DocType", doctype):
		return None
	meta = frappe.get_meta(doctype)
	for fieldname in preferred:
		if fieldname and meta.has_field(fieldname):
			return fieldname
	for df in meta.fields:
		if df.fieldtype == "Attach":
			return df.fieldname
	return None


def load_cgm_task_template_items(template_name: str) -> list[dict]:
	"""Return ordered task rows from a CGM Task Template (includes extends_template chain)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		normalize_department_stem,
	)
	from cgm_shipping.cgm_worldwide_shipping.task_engine import _collect_items

	if not template_name:
		frappe.throw("CGM Task Template name is required.")
	if not frappe.db.exists("CGM Task Template", template_name):
		frappe.throw(f"CGM Task Template '{template_name}' not found.")

	template = frappe.get_doc("CGM Task Template", template_name)
	items = _collect_items(template)
	out: list[dict] = []
	for item in sorted(items, key=lambda row: row["sequence_no"]):
		subject = (item.get("subject") or "").strip()
		dept = normalize_department_stem(item.get("department_role"))
		if not subject:
			continue
		if not dept:
			frappe.throw(
				f"CGM Task Template '{template_name}': Department is required for task: {subject}"
			)
		out.append(
			{
				"subject": subject,
				"department": dept,
				"sequence_no": item["sequence_no"],
			}
		)

	if not out:
		frappe.throw(f"CGM Task Template '{template_name}' has no task items.")

	return out


def load_sea_task_template() -> list[dict[str, str]]:
	"""Return sea import tasks from CGM Task Template master."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_TEMPLATE,
	)

	return [
		{"subject": row["subject"], "department": row["department"]}
		for row in load_cgm_task_template_items(SEA_IMPORT_TEMPLATE)
	]


def load_sea_transit_import_task_template() -> list[dict]:
	"""Return composed sea transit import tasks from CGM Task Template."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_TEMPLATE,
		SEA_TRANSIT_IMPORT_TEMPLATE,
	)

	parent_count = len(load_cgm_task_template_items(SEA_IMPORT_TEMPLATE))
	rows = load_cgm_task_template_items(SEA_TRANSIT_IMPORT_TEMPLATE)
	composed: list[dict] = []
	for row in rows:
		composed.append(
			{
				**row,
				"shared": int(row["sequence_no"]) <= parent_count,
			}
		)
	return composed


def load_sea_transit_export_task_template() -> list[dict[str, str]]:
	"""Return sea transit export tasks from CGM Task Template."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_TRANSIT_EXPORT_TEMPLATE,
	)

	return [
		{"subject": row["subject"], "department": row["department"]}
		for row in load_cgm_task_template_items(SEA_TRANSIT_EXPORT_TEMPLATE)
	]
