"""Shipment Type configuration — single source of truth for transport documents.

All behaviour is read from Shipment Type master fields (transport_documents,
primary_transport_document, required_documents). No shipment-type name hardcoding.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	TRANSPORT_DOCUMENT_REGISTRY,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import get_shipment_type_record

TRANSPORT_DOC_TO_OPP_FIELD = {
	label: cfg["opp_field"]
	for label, cfg in TRANSPORT_DOCUMENT_REGISTRY.items()
	if cfg.get("opp_field")
}

TRANSPORT_DOC_TO_DOCTYPE = {
	label: cfg["doctype"] for label, cfg in TRANSPORT_DOCUMENT_REGISTRY.items()
}

PRIMARY_DOC_TO_OPP_FIELD = TRANSPORT_DOC_TO_OPP_FIELD
PRIMARY_DOC_TO_DOCTYPE = {
	label: cfg["doctype"]
	for label, cfg in TRANSPORT_DOCUMENT_REGISTRY.items()
	if cfg.get("opp_field")
}

# First document on sea shipments may be either of these; one is enough to Start Shipment.
START_GATE_ALTERNATES = frozenset({"Bill of Lading", "Booking Confirmation"})


def _transport_doctype_exists(label: str) -> bool:
	doctype = TRANSPORT_DOC_TO_DOCTYPE.get(label)
	return bool(doctype and frappe.db.exists("DocType", doctype))


def _transport_doc_entry(label: str, *, is_required: bool, sort_order: int) -> dict | None:
	if not label or label == "None" or not _transport_doctype_exists(label):
		return None
	return {
		"transport_document": label,
		"doctype": TRANSPORT_DOC_TO_DOCTYPE[label],
		"opp_field": TRANSPORT_DOC_TO_OPP_FIELD.get(label),
		"is_required_for_start": is_required,
		"sort_order": sort_order,
	}


def resolve_primary_transport_document(row: dict | None) -> str:
	"""Configured legacy primary document field on Shipment Type (no inference)."""
	if not row:
		return "None"
	value = (row.get("primary_transport_document") or "None").strip()
	return value or "None"


def _apply_primary_start_requirement(docs: list[dict], row: dict | None) -> list[dict]:
	"""Ensure Primary Transport Document is listed and counts toward Start Shipment.

	Do not demote other start-gate documents — BL and Booking Confirmation are
	interchangeable (whichever arrives first unlocks Start Shipment).
	"""
	primary = resolve_primary_transport_document(row)
	out = list(docs)
	if primary and primary != "None":
		labels = {item["transport_document"] for item in out}
		if primary not in labels:
			entry = _transport_doc_entry(primary, is_required=True, sort_order=0)
			if entry:
				out.insert(0, entry)
		for item in out:
			if item["transport_document"] == primary:
				item["is_required_for_start"] = True

	# Sea start-gate alternates: both count toward Start Shipment (OR).
	labels = {item["transport_document"] for item in out}
	if labels & START_GATE_ALTERNATES:
		for item in out:
			if item["transport_document"] in START_GATE_ALTERNATES:
				item["is_required_for_start"] = True

	return sorted(out, key=lambda item: (item["sort_order"], item["transport_document"]))


def derive_transport_documents_from_flags(row: dict | None) -> list[dict]:
	"""Build default transport document rows from Shipment Type master flags (not names)."""
	if not row:
		return []

	mode = (row.get("default_mode_of_transport") or "").strip().lower()
	outbound = bool(row.get("is_outbound")) or bool(row.get("uses_export_documents"))
	transit = bool(row.get("uses_transit_documents"))

	rows: list[tuple[str, int, bool]] = []

	# Outbound before transit. BL and Booking Confirmation are both start-capable (OR).
	if mode == "air" and not outbound:
		rows.append(("Air Waybill", 1, True))
	elif outbound:
		rows.append(("Booking Confirmation", 1, True))
		rows.append(("Bill of Lading", 2, True))
	elif transit:
		sort_order = 1
		if _transport_doctype_exists("Release Order"):
			rows.append(("Release Order", sort_order, False))
			sort_order += 1
		rows.append(("Bill of Lading", sort_order, True))
		rows.append(("Booking Confirmation", sort_order + 1, True))
	else:
		rows.append(("Bill of Lading", 1, True))
		rows.append(("Booking Confirmation", 2, True))

	out: list[dict] = []
	for label, sort_order, is_required in rows:
		entry = _transport_doc_entry(label, is_required=is_required, sort_order=sort_order)
		if entry:
			out.append(entry)
	return _apply_primary_start_requirement(out, row)


def _shipment_type_link_name(row: dict | None, shipment_type: str | None = None) -> str:
	"""Resolve Shipment Type document name from a get_value row."""
	if not row:
		return (shipment_type or "").strip()
	return (row.get("name") or row.get("shipment_type_name") or (shipment_type or "")).strip()


def get_allowed_transport_documents(shipment_type: str | None) -> list[dict]:
	"""Transport document actions from Shipment Type.transport_documents, with flag-based fallback."""
	row = get_shipment_type_record(shipment_type)
	st_name = _shipment_type_link_name(row, shipment_type)
	if not row or not st_name:
		return []

	configured: list[dict] = []
	meta = frappe.get_meta("Shipment Type")

	if meta.has_field("transport_documents") and frappe.db.exists("Shipment Type", st_name):
		st = frappe.get_doc("Shipment Type", st_name)
		for child in st.get("transport_documents") or []:
			entry = _transport_doc_entry(
				(child.get("transport_document") or "").strip(),
				is_required=bool(child.get("is_required_for_start")),
				sort_order=cint(child.get("sort_order")),
			)
			if entry:
				configured.append(entry)

	if configured:
		return _apply_primary_start_requirement(
			_merge_transport_documents(configured, row), row
		)

	return derive_transport_documents_from_flags(row)


def _merge_transport_documents(configured: list[dict], row: dict) -> list[dict]:
	"""Keep explicit Shipment Type rows and add any flag-derived documents not yet listed."""
	# Derive without primary remapping so we can merge labels, then apply primary once.
	derived_row = dict(row or {})
	derived_row["primary_transport_document"] = "None"
	derived = derive_transport_documents_from_flags(derived_row)
	existing = {item["transport_document"] for item in configured}
	merged = list(configured)
	for item in derived:
		if item["transport_document"] not in existing:
			merged.append(item)
	return sorted(merged, key=lambda item: (item["sort_order"], item["transport_document"]))


def ensure_shipment_type_transport_document_defaults() -> None:
	"""Persist transport_documents child rows when empty, derived from Shipment Type flags."""
	if not frappe.db.exists("DocType", "Shipment Type"):
		return

	meta = frappe.get_meta("Shipment Type")
	if not meta.has_field("transport_documents"):
		return

	fields = [
		"default_mode_of_transport",
		"is_outbound",
		"uses_export_documents",
		"uses_transit_documents",
	]
	fields = ["name"] + [field for field in fields if meta.has_field(field)]
	if meta.has_field("task_flow_key"):
		fields.append("task_flow_key")

	for row in frappe.get_all("Shipment Type", fields=fields):
		st_name = (row.get("name") or "").strip()
		if not st_name or not frappe.db.exists("Shipment Type", st_name):
			continue

		task_flow = (row.get("task_flow_key") or "").upper()
		name_u = st_name.upper()
		export_named = ("EXPORT" in name_u or "OUTBOUND" in name_u) and "IMPORT" not in name_u
		updates: dict = {}
		if (
			meta.has_field("is_outbound")
			and (
				"EXPORT" in task_flow
				or "OUTBOUND" in task_flow
				or export_named
				or bool(row.get("uses_export_documents"))
			)
			and not row.get("is_outbound")
		):
			updates["is_outbound"] = 1
		if (
			meta.has_field("uses_export_documents")
			and ("EXPORT" in task_flow or export_named)
			and not row.get("uses_export_documents")
		):
			updates["uses_export_documents"] = 1
		if (
			meta.has_field("uses_transit_documents")
			and "TRANSIT" in task_flow
			and not row.get("uses_transit_documents")
		):
			updates["uses_transit_documents"] = 1

		# Outbound / export shipments start with Booking Confirmation; BL attaches later.
		outbound_after = bool(row.get("is_outbound")) or bool(updates.get("is_outbound"))
		export_after = bool(row.get("uses_export_documents")) or bool(
			updates.get("uses_export_documents")
		)
		if (
			meta.has_field("primary_transport_document")
			and (outbound_after or export_after or "EXPORT" in task_flow or export_named)
			and (row.get("primary_transport_document") or "None").strip()
			in ("None", "", "Bill of Lading")
		):
			updates["primary_transport_document"] = "Booking Confirmation"

		if updates:
			frappe.db.set_value("Shipment Type", st_name, updates, update_modified=False)
			row.update(updates)

		if (
			meta.has_field("is_outbound")
			and meta.has_field("uses_export_documents")
			and row.get("uses_export_documents")
			and not row.get("is_outbound")
		):
			frappe.db.set_value(
				"Shipment Type", st_name, "is_outbound", 1, update_modified=False
			)
			row["is_outbound"] = 1

		st = frappe.get_doc("Shipment Type", st_name)
		defaults = derive_transport_documents_from_flags(row)
		if not defaults:
			continue

		existing = {
			(
				(r.transport_document or "").strip(),
				cint(r.sort_order),
				bool(r.is_required_for_start),
			)
			for r in (st.get("transport_documents") or [])
		}
		expected = {
			(item["transport_document"], item["sort_order"], item["is_required_for_start"])
			for item in defaults
		}
		if existing == expected:
			continue

		st.set("transport_documents", [])
		for item in defaults:
			st.append(
				"transport_documents",
				{
					"transport_document": item["transport_document"],
					"sort_order": item["sort_order"],
					"is_required_for_start": 1 if item["is_required_for_start"] else 0,
				},
			)
		st.save(ignore_permissions=True)
