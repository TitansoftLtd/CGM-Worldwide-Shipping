"""LP {qty}X{size}-{batch}/{seq} business reference for shipment Projects.

ERPNext keeps the internal document name (PROJ-####). The LP reference is stored on
project_name and custom_project_reference for user-facing display.
"""
from __future__ import annotations

import re

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	get_container_table_field_for_doctype,
)

LP_PROJECT_NAME_PATTERN = re.compile(
	r"^LP\s+(\d+)X(\d+)-(\d+)/(\d{4})$",
	re.IGNORECASE,
)
LEGACY_CGM_REF_PATTERN = re.compile(r"^CGM/[A-Z0-9]{2,5}\d{3}/\d{4}$", re.IGNORECASE)
LEGACY_PROJ_PATTERN = re.compile(r"^PROJ-(\d+)$", re.IGNORECASE)
QUANTITY_SUMMARY_PATTERN = re.compile(
	r"(\d+)\s*x\s*([A-Za-z0-9]+)",
	re.IGNORECASE,
)

PROJECT_REFERENCE_FIELD = "custom_project_reference"
LEGACY_REFERENCE_FIELD = "custom_cgm_ref_no"
PROJECT_NAME_LOCK = "cgm_lp_project_sequence"


def is_lp_project_reference(value: str | None) -> bool:
	if not value:
		return False
	return bool(LP_PROJECT_NAME_PATTERN.match(str(value).strip()))


def is_legacy_business_reference(value: str | None) -> bool:
	if not value:
		return False
	text = str(value).strip()
	if text.startswith("Shipment -"):
		return True
	if LEGACY_CGM_REF_PATTERN.match(text):
		return True
	return False


def project_reference_field(meta=None) -> str | None:
	meta = meta or frappe.get_meta("Project")
	if meta.has_field(PROJECT_REFERENCE_FIELD):
		return PROJECT_REFERENCE_FIELD
	if meta.has_field(LEGACY_REFERENCE_FIELD):
		return LEGACY_REFERENCE_FIELD
	return None


def get_project_reference(doc) -> str | None:
	"""User-facing LP (or legacy) reference from a Project document."""
	field = project_reference_field(doc.meta)
	if field:
		value = (doc.get(field) or "").strip()
		if value:
			return value
	project_name = (doc.get("project_name") or "").strip()
	if is_lp_project_reference(project_name) or is_legacy_business_reference(project_name):
		return project_name
	return None


def display_ref_from_values(row: dict) -> str:
	"""User-facing project reference from a get_all / get_value row."""
	ref = get_project_reference_from_values(row)
	return ref or row.get("name") or ""


def get_project_reference_from_values(row: dict) -> str | None:
	field = project_reference_field()
	if field:
		value = (row.get(field) or "").strip()
		if value:
			return value
	legacy = (row.get(LEGACY_REFERENCE_FIELD) or "").strip()
	if legacy:
		return legacy
	project_name = (row.get("project_name") or "").strip()
	if is_lp_project_reference(project_name) or is_legacy_business_reference(project_name):
		return project_name
	return None


def get_project_reference_by_name(project_name: str | None) -> str | None:
	if not project_name or not frappe.db.exists("Project", project_name):
		return None
	doc = frappe.get_doc("Project", project_name)
	return get_project_reference(doc) or doc.name


def should_auto_name_project(project) -> bool:
	"""True when insert should allocate LP …/NNNN on project_name + custom reference."""
	if is_lp_project_reference(project.get("project_name")):
		return False
	ref_field = project_reference_field(project.meta)
	if ref_field and is_lp_project_reference(project.get(ref_field)):
		return False
	name = (project.get("project_name") or "").strip()
	if not name:
		return True
	return is_legacy_business_reference(name)


def _normalize_container_size_code(label: str | None) -> str:
	text = (label or "").strip().upper()
	if not text:
		return "0"
	digits = re.sub(r"[^0-9]", "", text)
	return digits or text.replace("FT", "")


def _container_qty_size_from_rows(project) -> str | None:
	container_field = get_container_table_field_for_doctype("Project")
	if not container_field or not project.meta.has_field(container_field):
		return None

	counts: dict[str, int] = {}
	for row in project.get(container_field) or []:
		container_type = (row.get("type_of_container") or "").strip()
		if not container_type:
			continue
		counts[container_type] = counts.get(container_type, 0) + 1

	if not counts:
		return None

	dominant_type = max(counts, key=lambda key: (counts[key], key))
	qty = counts[dominant_type]
	size = _normalize_container_size_code(dominant_type)
	return f"{qty}X{size}"


def _container_qty_size_from_quantity_field(project) -> str | None:
	summary = (project.get("custom_quantity") or "").strip()
	if not summary:
		return None

	match = QUANTITY_SUMMARY_PATTERN.search(summary)
	if not match:
		return None
	qty, size_label = match.group(1), match.group(2)
	return f"{int(qty)}X{_normalize_container_size_code(size_label)}"


def container_qty_size_segment(project) -> str:
	"""Return e.g. 4X40 from container rows or custom_quantity."""
	return (
		_container_qty_size_from_rows(project)
		or _container_qty_size_from_quantity_field(project)
		or "0X0"
	)


def _sequence_from_reference(value: str | None) -> int | None:
	if not value:
		return None
	text = str(value).strip()
	match = LP_PROJECT_NAME_PATTERN.match(text)
	if match:
		return int(match.group(4))
	match = LEGACY_PROJ_PATTERN.match(text)
	if match:
		return int(match.group(1))
	return None


def _project_reference_query_fields() -> list[str]:
	fields = ["project_name"]
	if frappe.db.has_column("Project", PROJECT_REFERENCE_FIELD):
		fields.append(PROJECT_REFERENCE_FIELD)
	if frappe.db.has_column("Project", LEGACY_REFERENCE_FIELD):
		fields.append(LEGACY_REFERENCE_FIELD)
	return fields


def _scan_max_project_sequence() -> int:
	max_seq = 0
	field_list = ", ".join(f"`{field}`" for field in _project_reference_query_fields())
	rows = frappe.db.sql(f"SELECT {field_list} FROM `tabProject`", as_dict=True)
	for row in rows:
		for ref in row.values():
			seq = _sequence_from_reference(ref)
			if seq is not None:
				max_seq = max(max_seq, seq)
	return max_seq


def next_global_project_sequence() -> int:
	"""Highest /NNNN suffix across LP references + 1 (global, not per customer)."""
	frappe.db.sql("SELECT GET_LOCK(%s, 10)", (PROJECT_NAME_LOCK,))
	try:
		return _scan_max_project_sequence() + 1
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", (PROJECT_NAME_LOCK,))


def build_lp_project_reference(project, sequence: int | None = None) -> str:
	"""Format: LP 6X20-9/0083"""
	segment = container_qty_size_segment(project)
	batch = (project.get("custom_batch_no") or "0").strip() or "0"
	seq = sequence if sequence is not None else next_global_project_sequence()
	return f"LP {segment}-{batch}/{seq:04d}"


def _lp_reference_in_use(reference: str) -> bool:
	if frappe.db.exists("Project", {"project_name": reference}):
		return True
	if frappe.db.has_column("Project", PROJECT_REFERENCE_FIELD):
		if frappe.db.exists("Project", {PROJECT_REFERENCE_FIELD: reference}):
			return True
	if frappe.db.has_column("Project", LEGACY_REFERENCE_FIELD):
		if frappe.db.exists("Project", {LEGACY_REFERENCE_FIELD: reference}):
			return True
	return False


def sync_project_reference_fields(project, reference: str) -> None:
	project.project_name = reference
	ref_field = project_reference_field(project.meta)
	if ref_field:
		project.set(ref_field, reference)


def assign_lp_project_reference(project) -> str | None:
	"""Set project_name + custom_project_reference; leave ERPNext name (PROJ-####) unchanged."""
	if not should_auto_name_project(project):
		reference = get_project_reference(project)
		if reference:
			sync_project_reference_fields(project, reference)
		return reference

	seq = next_global_project_sequence()
	for _attempt in range(50):
		reference = build_lp_project_reference(project, sequence=seq)
		if not _lp_reference_in_use(reference):
			sync_project_reference_fields(project, reference)
			return reference
		seq += 1

	frappe.throw("Could not allocate a unique LP project reference.")


# Backward-compatible aliases used during refactor.
is_lp_project_name = is_lp_project_reference
build_lp_project_name = build_lp_project_reference
assign_lp_project_name = assign_lp_project_reference
