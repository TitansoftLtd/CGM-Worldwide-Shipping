"""Shipment Type master data — seed and lookup (replaces hardcoded prefix/mode maps)."""
from __future__ import annotations

import frappe

# Operational types from CGM tracking sheets (prefix = CGM/FCL001/1022 segment).
DEFAULT_SHIPMENT_TYPES: list[dict] = [
	{
		"shipment_type_name": "Sea FCL",
		"cgm_ref_prefix": "FCL",
		"default_mode_of_transport": "Sea",
		"use_sea_import_workflow": 1,
		"requires_bill_of_lading": 1,
		"description": "Full container load — port/CFS, containers table, 24-step sea clearance.",
	},
	{
		"shipment_type_name": "Sea LCL",
		"cgm_ref_prefix": "LCL",
		"default_mode_of_transport": "Sea",
		"use_sea_import_workflow": 1,
		"requires_bill_of_lading": 1,
		"description": "Less than container load — shared BL, sea clearance.",
	},
	{
		"shipment_type_name": "Air Import",
		"cgm_ref_prefix": "IM",
		"default_mode_of_transport": "Air",
		"requires_air_waybill": 1,
		"description": "Air import — CGM/IM001/0822 style references, AWB not BL.",
	},
	{
		"shipment_type_name": "Cross-Border Road Import",
		"cgm_ref_prefix": "CBIM",
		"default_mode_of_transport": "Road",
		"description": "Road import via border (e.g. Malaba) — CGM/CBIM001/0523, truck rows.",
	},
	{
		"shipment_type_name": "Motor Vehicle Import",
		"cgm_ref_prefix": "MVS",
		"default_mode_of_transport": "Sea",
		"requires_bill_of_lading": 1,
		"description": "Used vehicle / unit tracking at port — CGM/MVS001/0223 sheet.",
	},
	{
		"shipment_type_name": "Export",
		"cgm_ref_prefix": "EX",
		"default_mode_of_transport": "Sea",
		"description": "Export clearance — CGM/EX001/0523.",
	},
	{
		"shipment_type_name": "Transit",
		"cgm_ref_prefix": "FCL",
		"default_mode_of_transport": "Sea",
		"use_sea_import_workflow": 1,
		"requires_bill_of_lading": 1,
		"description": "Transit containers (often FCL ref series) — TZ/UG/RW border moves.",
	},
]

_OPTIONAL_SHIPMENT_TYPE_FIELDS = (
	"use_sea_import_workflow",
	"requires_bill_of_lading",
	"requires_air_waybill",
	"is_active",
	"description",
)


def _shipment_type_meta():
	if not frappe.db.exists("DocType", "Shipment Type"):
		return None
	return frappe.get_meta("Shipment Type")


def _shipment_type_query_fields() -> list[str]:
	"""Only fields present in DB — safe before bench migrate adds new columns."""
	base = ["name", "shipment_type_name", "cgm_ref_prefix", "default_mode_of_transport"]
	meta = _shipment_type_meta()
	if not meta:
		return base
	return base + [f for f in _OPTIONAL_SHIPMENT_TYPE_FIELDS if meta.has_field(f)]


def _filter_row_for_doc(row: dict) -> dict:
	meta = _shipment_type_meta()
	if not meta:
		return row
	return {k: v for k, v in row.items() if meta.has_field(k)}


def seed_shipment_types() -> list[str]:
	"""Insert/update Shipment Type rows from DEFAULT_SHIPMENT_TYPES."""
	if not frappe.db.exists("DocType", "Shipment Type"):
		return []

	meta = _shipment_type_meta()
	created_or_updated = []
	for row in DEFAULT_SHIPMENT_TYPES:
		payload = _filter_row_for_doc(row)
		name = row["shipment_type_name"]
		if frappe.db.exists("Shipment Type", name):
			doc = frappe.get_doc("Shipment Type", name)
			changed = False
			for key, value in payload.items():
				if doc.get(key) != value:
					doc.set(key, value)
					changed = True
			if meta and meta.has_field("is_active") and not doc.get("is_active"):
				doc.is_active = 1
				changed = True
			if changed:
				doc.save(ignore_permissions=True)
				created_or_updated.append(name)
		else:
			doc = frappe.new_doc("Shipment Type")
			doc.update(payload)
			if meta and meta.has_field("is_active"):
				doc.is_active = 1
			doc.insert(ignore_permissions=True)
			created_or_updated.append(name)

	# Drop orphan hash-named row if Sea LCL was created properly.
	orphan = "qrivef3l3t"
	if frappe.db.exists("Shipment Type", orphan) and frappe.db.exists("Shipment Type", "Sea LCL"):
		frappe.delete_doc("Shipment Type", orphan, ignore_permissions=True)

	frappe.clear_cache(doctype="Shipment Type")
	return created_or_updated


def get_shipment_type_record(shipment_type: str | None) -> dict | None:
	"""Load Shipment Type by Link name or shipment_type_name label."""
	if not shipment_type:
		return None
	st = str(shipment_type).strip()
	if not st:
		return None

	aliases = {"Road Import": "Cross-Border Road Import"}
	st = aliases.get(st, st)

	fields = _shipment_type_query_fields()
	meta = _shipment_type_meta()

	if frappe.db.exists("Shipment Type", st):
		return frappe.db.get_value("Shipment Type", st, fields, as_dict=True)

	filters: dict = {"shipment_type_name": st}
	if meta and meta.has_field("is_active"):
		filters["is_active"] = 1

	return frappe.db.get_value("Shipment Type", filters, fields, as_dict=True)


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
