"""One-time bootstrap data for Shipment Type master (not used at runtime)."""
from __future__ import annotations

import frappe

# Operational types from CGM tracking sheets (prefix = CGM/FCL001/1022 segment).
SHIPMENT_TYPE_BOOTSTRAP_DATA: list[dict] = [
	{
		"shipment_type_name": "Sea FCL",
		"cgm_ref_prefix": "FCL",
		"default_mode_of_transport": "Sea",
		"use_sea_import_workflow": 1,
		"requires_bill_of_lading": 1,
		"description": "Full container load - port/CFS, containers table, 24-step sea clearance.",
	},
	{
		"shipment_type_name": "Sea LCL",
		"cgm_ref_prefix": "LCL",
		"default_mode_of_transport": "Sea",
		"use_sea_import_workflow": 1,
		"requires_bill_of_lading": 1,
		"description": "Less than container load - shared BL, sea clearance.",
	},
	{
		"shipment_type_name": "Air Import",
		"cgm_ref_prefix": "IM",
		"default_mode_of_transport": "Air",
		"requires_air_waybill": 1,
		"description": "Air import - CGM/IM001/0822 style references, AWB not BL.",
	},
	{
		"shipment_type_name": "Cross-Border Road Import",
		"cgm_ref_prefix": "CBIM",
		"default_mode_of_transport": "Road",
		"description": "Road import via border (e.g. Malaba) - CGM/CBIM001/0523, truck rows.",
	},
	{
		"shipment_type_name": "Motor Vehicle Import",
		"cgm_ref_prefix": "MVS",
		"default_mode_of_transport": "Sea",
		"requires_bill_of_lading": 1,
		"description": "Used vehicle / unit tracking at port - CGM/MVS001/0223 sheet.",
	},
	{
		"shipment_type_name": "Export",
		"cgm_ref_prefix": "EX",
		"default_mode_of_transport": "Sea",
		"description": "Export clearance - CGM/EX001/0523.",
	},
	{
		"shipment_type_name": "Transit",
		"cgm_ref_prefix": "FCL",
		"default_mode_of_transport": "Sea",
		"use_sea_import_workflow": 1,
		"requires_bill_of_lading": 1,
		"description": "Transit containers (often FCL ref series) - TZ/UG/RW border moves.",
	},
]

_FLAG_FIELDS = frozenset(
	{
		"requires_bill_of_lading",
		"requires_air_waybill",
		"use_sea_import_workflow",
		"uses_unit_tracking",
		"is_active",
	}
)


def _shipment_type_meta():
	if not frappe.db.exists("DocType", "Shipment Type"):
		return None
	return frappe.get_meta("Shipment Type")


def _filter_row_for_doc(row: dict) -> dict:
	meta = _shipment_type_meta()
	if not meta:
		return row
	return {k: v for k, v in row.items() if meta.has_field(k)}


def _should_apply_bootstrap_value(doc, key: str, value, *, only_fill_empty_fields: bool) -> bool:
	if doc.get(key) == value:
		return False
	if not only_fill_empty_fields:
		return True
	if key in _FLAG_FIELDS:
		return False
	return doc.get(key) in (None, "")


def _shipment_type_docname(label: str) -> str | None:
	"""Resolve Shipment Type by Link name or unique shipment_type_name."""
	st = (label or "").strip()
	if not st:
		return None
	if frappe.db.exists("Shipment Type", st):
		return st
	return frappe.db.get_value("Shipment Type", {"shipment_type_name": st}, "name")


def _rename_shipment_type_to_label(docname: str, label: str) -> str:
	"""Align document name with shipment_type_name when autoname allows."""
	if docname == label:
		return docname
	if frappe.db.exists("Shipment Type", label):
		return docname
	frappe.rename_doc("Shipment Type", docname, label, force=True)
	return label


def _remove_duplicate_shipment_type_names() -> None:
	"""Drop hash-named rows when a properly named row shares shipment_type_name."""
	if not frappe.db.exists("DocType", "Shipment Type"):
		return
	for row in frappe.get_all(
		"Shipment Type",
		fields=["name", "shipment_type_name"],
	):
		label = (row.shipment_type_name or "").strip()
		if not label or row.name == label:
			continue
		if frappe.db.exists("Shipment Type", label):
			frappe.delete_doc("Shipment Type", row.name, ignore_permissions=True)


def bootstrap_shipment_types(*, only_fill_empty_fields: bool = True) -> list[str]:
	"""Insert missing Shipment Type rows; optionally fill only empty scalar fields on existing rows."""
	if not frappe.db.exists("DocType", "Shipment Type"):
		return []

	meta = _shipment_type_meta()
	created_or_updated = []
	for row in SHIPMENT_TYPE_BOOTSTRAP_DATA:
		payload = _filter_row_for_doc(row)
		label = row["shipment_type_name"]
		docname = _shipment_type_docname(label)
		if docname:
			doc = frappe.get_doc("Shipment Type", docname)
			changed = False
			for key, value in payload.items():
				if not _should_apply_bootstrap_value(
					doc, key, value, only_fill_empty_fields=only_fill_empty_fields
				):
					continue
				doc.set(key, value)
				changed = True
			if changed:
				doc.save(ignore_permissions=True)
				created_or_updated.append(label)
			_rename_shipment_type_to_label(doc.name, label)
		else:
			doc = frappe.new_doc("Shipment Type")
			doc.update(payload)
			if meta and meta.has_field("is_active"):
				doc.is_active = 1
			doc.insert(ignore_permissions=True)
			created_or_updated.append(label)

	_remove_duplicate_shipment_type_names()

	frappe.clear_cache(doctype="Shipment Type")
	return created_or_updated
