"""Shipment Type interpretation layer - DB is source of truth; no bootstrap constants at runtime."""
from __future__ import annotations

import frappe

_OPTIONAL_SHIPMENT_TYPE_FIELDS = (
	"use_sea_import_workflow",
	"requires_bill_of_lading",
	"requires_air_waybill",
	"uses_unit_tracking",
	"default_mode_of_transport",
	"is_active",
	"description",
)

_LEGACY_ALIASES = {"Road Import": "Cross-Border Road Import"}


def _shipment_type_meta():
	if not frappe.db.exists("DocType", "Shipment Type"):
		return None
	return frappe.get_meta("Shipment Type")


def _shipment_type_field_queryable(fieldname: str) -> bool:
	meta = _shipment_type_meta()
	if not meta or not meta.has_field(fieldname):
		return False
	return frappe.db.has_column("Shipment Type", fieldname)


def _shipment_type_query_fields() -> list[str]:
	candidates = [
		"name",
		"shipment_type_name",
		"cgm_ref_prefix",
		*_OPTIONAL_SHIPMENT_TYPE_FIELDS,
	]
	return [f for f in candidates if _shipment_type_field_queryable(f)] or ["name"]


def _normalize_shipment_type_name(shipment_type: str | None) -> str | None:
	if not shipment_type:
		return None
	st = str(shipment_type).strip()
	if not st:
		return None
	return _LEGACY_ALIASES.get(st, st)


def get_shipment_type_record(shipment_type: str | None) -> dict | None:
	"""Load Shipment Type by Link name or shipment_type_name label."""
	st = _normalize_shipment_type_name(shipment_type)
	if not st:
		return None

	fields = _shipment_type_query_fields()
	meta = _shipment_type_meta()

	if frappe.db.exists("Shipment Type", st):
		return frappe.db.get_value("Shipment Type", st, fields, as_dict=True)

	filters: dict = {"shipment_type_name": st}
	if meta and meta.has_field("is_active") and _shipment_type_field_queryable("is_active"):
		filters["is_active"] = 1

	return frappe.db.get_value("Shipment Type", filters, fields, as_dict=True)


@frappe.request_cache
def get_allowed_shipment_types() -> tuple[str, ...]:
	"""Active Shipment Type link names from DB."""
	if not frappe.db.exists("DocType", "Shipment Type"):
		return ()
	filters: dict = {}
	if _shipment_type_field_queryable("is_active"):
		filters["is_active"] = 1
	return tuple(
		frappe.get_all("Shipment Type", filters=filters, pluck="name", order_by="name asc")
	)


def validate_shipment_type_exists(shipment_type: str | None) -> None:
	"""Reject unknown shipment types when the master DocType is configured."""
	st = _normalize_shipment_type_name(shipment_type)
	if not st or not frappe.db.exists("DocType", "Shipment Type"):
		return
	if get_shipment_type_record(st):
		return
	allowed = get_allowed_shipment_types()
	preview = ", ".join(allowed[:12])
	suffix = f" (+{len(allowed) - 12} more)" if len(allowed) > 12 else ""
	frappe.throw(
		f"Unknown shipment type: {st}. Configure it in Shipment Type"
		f"{f' or choose: {preview}{suffix}' if preview else ''}."
	)


def is_sea_import_enabled(shipment_type: str | None) -> bool:
	"""True when the Shipment Type master flags sea import workflow (or mode fallback)."""
	row = get_shipment_type_record(shipment_type)
	if not row:
		return False
	if _shipment_type_field_queryable("use_sea_import_workflow"):
		return bool(row.get("use_sea_import_workflow"))
	if _shipment_type_field_queryable("default_mode_of_transport"):
		return (row.get("default_mode_of_transport") or "").strip() == "Sea"
	return False


def sea_import_enabled_for_project(project) -> bool:
	"""Project-level sea import gate: master flag when typed, else legacy mode-of-transport."""
	shipment_type = project.get("custom_shipment_type") if hasattr(project, "get") else None
	if shipment_type:
		if is_sea_import_enabled(shipment_type):
			return True
		if _shipment_type_field_queryable("use_sea_import_workflow") and get_shipment_type_record(
			shipment_type
		):
			return False
	mode = project.get("custom_mode_of_transport") if hasattr(project, "get") else None
	return (mode or "").strip() == "Sea"


def requires_bill_of_lading(shipment_type: str | None) -> bool:
	row = get_shipment_type_record(shipment_type)
	return bool(row and row.get("requires_bill_of_lading"))


def requires_air_waybill(shipment_type: str | None) -> bool:
	row = get_shipment_type_record(shipment_type)
	return bool(row and row.get("requires_air_waybill"))


def cgm_ref_prefix_from_master(shipment_type: str | None, mode: str | None = None) -> str | None:
	row = get_shipment_type_record(shipment_type)
	if row and row.get("cgm_ref_prefix"):
		return str(row.cgm_ref_prefix).strip().upper()
	return None


def mode_from_master(shipment_type: str | None) -> str | None:
	row = get_shipment_type_record(shipment_type)
	if row and row.get("default_mode_of_transport"):
		return str(row.default_mode_of_transport).strip()
	return None
