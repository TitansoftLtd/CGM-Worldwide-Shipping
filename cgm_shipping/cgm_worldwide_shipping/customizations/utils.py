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


def load_sea_task_template() -> list[dict[str, str]]:
	"""Return sea import tasks from CGM Shipping Settings."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		normalize_department_stem,
	)

	settings = frappe.get_single("CGM Shipping Settings")
	rows = sorted(settings.get("custom_sea_import_task_template") or [], key=lambda r: r.idx or 0)

	out: list[dict[str, str]] = []
	for row in rows:
		subject = (row.task_subject or "").strip()
		dept = normalize_department_stem(row.department)
		if not subject:
			continue
		if not dept:
			frappe.throw(f"Sea import task template: Department is required for task: {subject}")
		out.append({"subject": subject, "department": dept})

	if not out:
		frappe.throw("Add at least one row to Sea import task template in CGM Shipping Settings.")

	return out


def load_sea_transit_import_task_template() -> list[dict]:
	"""Compose shared sea-import steps + transit extension from CGM Shipping Settings."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.inspection import (
		sea_import_task_sequence_no,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		normalize_department_stem,
	)

	settings = frappe.get_single("CGM Shipping Settings")
	shared_through = int(settings.get("custom_sea_transit_import_shared_through_seq") or 20)

	composed: list[dict] = []
	for idx, row in enumerate(load_sea_task_template(), start=1):
		seq = sea_import_task_sequence_no(idx)
		if seq > shared_through:
			break
		composed.append({**row, "sequence_no": seq, "shared": True})

	next_seq = shared_through + 1
	for row in sorted(
		settings.get("custom_sea_transit_import_extension_template") or [],
		key=lambda r: r.idx or 0,
	):
		subject = (row.task_subject or "").strip()
		dept = normalize_department_stem(row.department)
		if not subject:
			continue
		if not dept:
			frappe.throw(f"Sea transit import extension: Department is required for task: {subject}")
		composed.append(
			{
				"subject": subject,
				"department": dept,
				"sequence_no": next_seq,
				"shared": False,
			}
		)
		next_seq += 1

	if not composed:
		frappe.throw(
			"Configure Sea Transit Import extension template in CGM Shipping Settings."
		)
	return composed


def load_sea_transit_export_task_template() -> list[dict[str, str]]:
	"""Return sea transit export tasks from CGM Shipping Settings."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
		normalize_department_stem,
	)

	settings = frappe.get_single("CGM Shipping Settings")
	rows = sorted(
		settings.get("custom_sea_transit_export_task_template") or [],
		key=lambda r: r.idx or 0,
	)

	out: list[dict[str, str]] = []
	for row in rows:
		subject = (row.task_subject or "").strip()
		dept = normalize_department_stem(row.department)
		if not subject:
			continue
		if not dept:
			frappe.throw(f"Sea transit export task template: Department is required for task: {subject}")
		out.append({"subject": subject, "department": dept})

	if not out:
		frappe.throw(
			"Add at least one row to Sea Transit Export task template in CGM Shipping Settings."
		)
	return out
