"""Business project reference for shipment Projects.

ERPNext keeps the internal document name (PROJ-####). The business reference is
stored on project_name and custom_project_reference for user-facing display.

Formats:
  FCL:     {Client Reference} / {qty}X{size} / {batch}   e.g. PO-99 / 3X20 / 1
  Packages:{Client Reference} / {qty} {type}             e.g. PO-99 / 10 Cartons

Legacy LP {qty}X{size}-{batch}/{seq} names are still recognized but not allocated.
"""
from __future__ import annotations

import re

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch import (
	is_fcl_cargo_type,
	is_lcl_cargo_type,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import container_row_cargo_size
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	get_container_table_field_for_doctype,
)

# Legacy: LP 3X20-1/0109
LP_PROJECT_NAME_PATTERN = re.compile(
	r"^LP\s+(\d+)X(\d+)-(\d+)/(\d{4})$",
	re.IGNORECASE,
)
# FCL: Client Ref / 3X20 / 1  (optional / N disambiguator)
FCL_PROJECT_NAME_PATTERN = re.compile(
	r"^.+\s/\s(\d+)X(\d+)\s/\s(\d+)(?:\s/\s(\d+))?$",
	re.IGNORECASE,
)
# Package-based: Client Ref / 10 Cartons  (optional / N disambiguator)
PACKAGE_PROJECT_NAME_PATTERN = re.compile(
	r"^.+\s/\s.+(?:\s/\s\d+)?$",
)
LEGACY_CGM_REF_PATTERN = re.compile(r"^CGM/[A-Z0-9]{2,5}\d{3}/\d{4}$", re.IGNORECASE)
LEGACY_PROJ_PATTERN = re.compile(r"^PROJ-(\d+)$", re.IGNORECASE)
QUANTITY_SUMMARY_PATTERN = re.compile(
	r"(\d+)\s*x\s*([A-Za-z0-9]+)",
	re.IGNORECASE,
)

PROJECT_REFERENCE_FIELD = "custom_project_reference"
LEGACY_REFERENCE_FIELD = "custom_cgm_ref_no"
PROJECT_NAME_LOCK = "cgm_project_reference_lock"
CLIENT_REFERENCE_FIELD = "custom_client_refrence_no"
PROJECT_REFERENCE_INPUT_FIELDS = (
	CLIENT_REFERENCE_FIELD,
	"custom_batch_no",
	"custom_cargo_type",
	"custom_quantity",
	"custom_number_of_packages",
	"custom_package_type",
)


def is_lp_project_reference(value: str | None) -> bool:
	"""True for current or legacy business project references."""
	if not value:
		return False
	text = str(value).strip()
	if LP_PROJECT_NAME_PATTERN.match(text):
		return True
	if FCL_PROJECT_NAME_PATTERN.match(text):
		return True
	# Package format: must contain " / " and not look like a free-form title.
	if " / " in text and PACKAGE_PROJECT_NAME_PATTERN.match(text):
		return True
	return False


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
	"""User-facing business (or legacy) reference from a Project document."""
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
	"""True when insert should allocate a business reference on project_name."""
	if is_lp_project_reference(project.get("project_name")):
		return False
	ref_field = project_reference_field(project.meta)
	if ref_field and is_lp_project_reference(project.get(ref_field)):
		return False
	name = (project.get("project_name") or "").strip()
	if not name:
		return True
	return is_legacy_business_reference(name)


def _normalize_cargo_size_code(label: str | None) -> str:
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
		cargo_type = container_row_cargo_size(row)
		if not cargo_type:
			continue
		counts[cargo_type] = counts.get(cargo_type, 0) + 1

	if not counts:
		return None

	dominant_type = max(counts, key=lambda key: (counts[key], key))
	qty = counts[dominant_type]
	size = _normalize_cargo_size_code(dominant_type)
	return f"{qty}X{size}"


def _container_qty_size_from_quantity_field(project) -> str | None:
	summary = (project.get("custom_quantity") or "").strip()
	if not summary:
		return None

	match = QUANTITY_SUMMARY_PATTERN.search(summary)
	if not match:
		return None
	qty, size_label = match.group(1), match.group(2)
	return f"{int(qty)}X{_normalize_cargo_size_code(size_label)}"


def container_qty_size_segment(project) -> str:
	"""Return e.g. 4X40 from container rows or custom_quantity."""
	return (
		_container_qty_size_from_rows(project)
		or _container_qty_size_from_quantity_field(project)
		or "0X0"
	)


def package_quantity_segment(project) -> str | None:
	"""Return e.g. '10 Cartons' from package fields or non-container quantity."""
	pkgs = (project.get("custom_number_of_packages") or "").strip()
	ptype = (project.get("custom_package_type") or "").strip()
	if pkgs or ptype:
		return f"{pkgs} {ptype}".strip()

	summary = (project.get("custom_quantity") or "").strip()
	if summary and not QUANTITY_SUMMARY_PATTERN.search(summary):
		return summary
	return None


def _client_reference(project) -> str:
	ref = (project.get(CLIENT_REFERENCE_FIELD) or "").strip()
	if not ref:
		frappe.throw(
			frappe._(
				"Client Reference No is required to name the Project "
				"(format: Client Reference / Quantity / Batch)."
			),
			title=frappe._("Missing Client Reference"),
		)
	return ref


def _uses_package_naming(project) -> bool:
	cargo_type = project.get("custom_cargo_type")
	if is_lcl_cargo_type(cargo_type):
		return True
	if is_fcl_cargo_type(cargo_type):
		return False
	# Air / other package-only shipments: prefer packages when present.
	return bool(package_quantity_segment(project))


def _sequence_from_reference(value: str | None) -> int | None:
	"""Legacy helper: extract /NNNN from old LP names or PROJ-####."""
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
	"""Highest legacy /NNNN suffix across LP references + 1 (kept for compatibility)."""
	frappe.db.sql("SELECT GET_LOCK(%s, 10)", (PROJECT_NAME_LOCK,))
	try:
		return _scan_max_project_sequence() + 1
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", (PROJECT_NAME_LOCK,))


def build_lp_project_reference(project, sequence: int | None = None) -> str:
	"""Build business reference.

	``sequence`` is treated as an optional disambiguator (2, 3, …) when the
	base name is already in use — not the old global /0109 counter.
	"""
	client = _client_reference(project)

	if _uses_package_naming(project):
		qty = package_quantity_segment(project) or "0 Packages"
		base = f"{client} / {qty}"
	else:
		segment = container_qty_size_segment(project)
		batch = (project.get("custom_batch_no") or "0").strip() or "0"
		base = f"{client} / {segment} / {batch}"

	if sequence is not None and int(sequence) > 1:
		return f"{base} / {int(sequence)}"
	return base


def _project_name_for_reference(reference: str, exclude_name: str | None = None) -> str | None:
	"""Return the Project ``name`` using ``reference`` as project_name, if any."""
	if not reference:
		return None
	filters: dict = {"project_name": reference}
	if exclude_name:
		filters["name"] = ["!=", exclude_name]
	match = frappe.db.get_value("Project", filters, "name")
	if match:
		return match
	return None


def _reference_field_owner(reference: str, field: str, exclude_name: str | None = None) -> str | None:
	if not reference or not frappe.db.has_column("Project", field):
		return None
	filters: dict = {field: reference}
	if exclude_name:
		filters["name"] = ["!=", exclude_name]
	return frappe.db.get_value("Project", filters, "name")


def _lp_reference_in_use(reference: str, exclude_name: str | None = None) -> bool:
	if _project_name_for_reference(reference, exclude_name):
		return True
	if _reference_field_owner(reference, PROJECT_REFERENCE_FIELD, exclude_name):
		return True
	if _reference_field_owner(reference, LEGACY_REFERENCE_FIELD, exclude_name):
		return True
	return False


def project_reference_inputs_changed(project) -> bool:
	"""True when shipment fields that feed project_name were edited on save."""
	if project.is_new():
		return False
	prev = project.get_doc_before_save()
	if not prev:
		return False
	for fieldname in PROJECT_REFERENCE_INPUT_FIELDS:
		if project.meta.has_field(fieldname) and project.has_value_changed(fieldname):
			return True
	return False


def allocate_unique_lp_project_reference(
	project, *, exclude_name: str | None = None
) -> str:
	"""Build a unique Client Ref / Quantity[/ Batch] reference for ``project``."""
	frappe.db.sql("SELECT GET_LOCK(%s, 10)", (PROJECT_NAME_LOCK,))
	try:
		for attempt in range(1, 51):
			disambiguator = attempt if attempt > 1 else None
			reference = build_lp_project_reference(project, sequence=disambiguator)
			if not _lp_reference_in_use(reference, exclude_name=exclude_name):
				return reference
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", (PROJECT_NAME_LOCK,))

	frappe.throw(frappe._("Could not allocate a unique project reference."))


def sync_project_reference_fields(project, reference: str) -> None:
	project.project_name = reference
	ref_field = project_reference_field(project.meta)
	if ref_field:
		setattr(project, ref_field, reference)


def refresh_project_reference_from_fields(project) -> str | None:
	"""Rebuild project_name when Client Ref, batch, or quantity fields change on save."""
	if project.is_new():
		return None
	if not (project.get(CLIENT_REFERENCE_FIELD) or "").strip():
		return None
	if not project_reference_inputs_changed(project):
		return get_project_reference(project)

	reference = allocate_unique_lp_project_reference(project, exclude_name=project.name)
	sync_project_reference_fields(project, reference)
	return reference


def assign_lp_project_reference(project) -> str | None:
	"""Set project_name + custom_project_reference; leave ERPNext name (PROJ-####) unchanged."""
	if not should_auto_name_project(project):
		reference = get_project_reference(project)
		if reference:
			sync_project_reference_fields(project, reference)
		return reference

	reference = allocate_unique_lp_project_reference(
		project, exclude_name=project.name if not project.is_new() else None
	)
	sync_project_reference_fields(project, reference)
	return reference


# Backward-compatible aliases used during refactor.
is_lp_project_name = is_lp_project_reference
build_lp_project_name = build_lp_project_reference
assign_lp_project_name = assign_lp_project_reference
