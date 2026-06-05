"""Load container rows from a linked Bill of Lading."""
from __future__ import annotations

import frappe

CONTAINER_ROW_FIELDS = ("container_number", "type_of_container", "no_container", "seal_no")
BL_LINK_FIELD = "custom_bill_of_lading"
CONTAINER_TABLE_FIELD = "custom_container_information"
CONTAINER_TYPE_DISPLAY_ORDER = ("40FT", "20FT", "LCL")


def _container_type_key(container_type: str) -> str:
	return container_type.strip().upper()


def _container_type_label(container_type: str) -> str:
	key = _container_type_key(container_type)
	if key == "40FT":
		return "40FT"
	if key == "20FT":
		return "20FT"
	if key == "LCL":
		return "LCL"
	return container_type.strip()


def _fetch_container_rows(bill_of_lading: str | None) -> list[dict]:
	if not bill_of_lading or not frappe.db.exists("Bill of Lading", bill_of_lading):
		return []
	return frappe.get_all(
		"Container",
		filters={"parent": bill_of_lading, "parenttype": "Bill of Lading"},
		fields=list(CONTAINER_ROW_FIELDS),
		order_by="idx asc",
	)


@frappe.whitelist()
def get_bl_container_select_options(bill_of_lading: str | None = None) -> list[dict]:
	"""Options for Container Tracker select: value = container_number, label = human-readable."""
	rows = _fetch_container_rows(bill_of_lading)
	if bill_of_lading and frappe.db.exists("Bill of Lading", bill_of_lading):
		frappe.has_permission("Bill of Lading", ptype="read", doc=bill_of_lading, throw=True)

	options = []
	for row in rows:
		number = (row.get("container_number") or "").strip()
		if not number:
			continue
		parts = [number]
		if row.get("type_of_container"):
			parts.append(str(row.type_of_container))
		if row.get("seal_no"):
			parts.append(f"Seal {row.seal_no}")
		options.append({"value": number, "label": " — ".join(parts)})
	return options


def summarize_bl_container_quantities(bill_of_lading: str | None) -> str:
	"""Return e.g. '6 x 40FT, 7 x 20FT, 2 x LCL' from submitted BL container rows."""
	rows = _fetch_container_rows(bill_of_lading)
	if not rows:
		return ""

	counts: dict[str, int] = {}
	labels: dict[str, str] = {}
	for row in rows:
		container_type = (row.get("type_of_container") or "").strip()
		if not container_type:
			continue
		key = _container_type_key(container_type)
		counts[key] = counts.get(key, 0) + 1
		labels[key] = _container_type_label(container_type)

	if not counts:
		return ""

	ordered_keys: list[str] = [key for key in CONTAINER_TYPE_DISPLAY_ORDER if key in counts]
	for key in sorted(counts):
		if key not in ordered_keys:
			ordered_keys.append(key)

	return ", ".join(f"{counts[key]} x {labels[key]}" for key in ordered_keys)


@frappe.whitelist()
def get_container_rows_for_bill_of_lading(bill_of_lading: str | None = None) -> list[dict]:
	if not bill_of_lading:
		return []
	if not frappe.db.exists("Bill of Lading", bill_of_lading):
		return []

	frappe.has_permission("Bill of Lading", ptype="read", doc=bill_of_lading, throw=True)
	return _fetch_container_rows(bill_of_lading)


def sync_preshipment_containers_from_bl(doc, method=None) -> None:
	"""Populate read-only container rows from the linked Bill of Lading before save."""
	if not doc.meta.has_field(CONTAINER_TABLE_FIELD):
		return

	bl_name = doc.get(BL_LINK_FIELD)
	rows = _fetch_container_rows(bl_name) if bl_name else []
	doc.set(CONTAINER_TABLE_FIELD, [])
	for row in rows:
		doc.append(
			CONTAINER_TABLE_FIELD,
			{k: row.get(k) or "" for k in CONTAINER_ROW_FIELDS},
		)


def apply_bill_of_lading_from_source(target_doc, source_doc) -> None:
	"""Copy Bill of Lading link and container rows from Lead/Opportunity onto Project."""
	if not source_doc or not target_doc.meta.has_field(BL_LINK_FIELD):
		return

	bl_name = source_doc.get(BL_LINK_FIELD)
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return

	target_doc.set(BL_LINK_FIELD, bl_name)
	sync_preshipment_containers_from_bl(target_doc)

	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		carry_bill_of_lading_attachment_to_project,
	)

	carry_bill_of_lading_attachment_to_project(
		target_doc, bl_name=bl_name, source_doc=source_doc
	)
