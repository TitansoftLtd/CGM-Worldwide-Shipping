"""Shipment reference, BL/AWB sync, and CRM hooks."""
from __future__ import annotations


# ==================== CGM reference and shipment classification ====================

"""CGM tracking-sheet reference generation and shipment-type/mode classification.

Depends only on frappe, so it has no import cycle with utils - which re-exports
these names for callers that still import them from
cgm_shipping...customizations.utils.
"""

# from __future__ import annotations

import re

import frappe
from frappe.utils import getdate, today

# ─── Shipment Type master lookups ─────────────────────────────────────────────
# DB is the source of truth; read the Shipment Type master defensively so missing
# optional columns never break a save.

_OPTIONAL_SHIPMENT_TYPE_FIELDS = (
	"requires_bill_of_lading",
	"requires_air_waybill",
	"uses_unit_tracking",
	"uses_container_tracking",
	"uses_transit_documents",
	"uses_destination_entry",
	"uses_export_documents",
	"is_outbound",
	"primary_transport_document",
	"task_flow_key",
	"task_template",
	"container_tracker_mode",
	"default_mode_of_transport",
	"cgm_ref_prefix",
	"legacy_crm_labels",
	"container_tracking_mode",
	"is_active",
	"description",
)


def _parse_label_lines(value: str | None) -> list[str]:
	if not value:
		return []
	return [line.strip() for line in str(value).splitlines() if line.strip()]


def resolve_shipment_type_from_legacy(label: str | None, mode: str | None = None) -> str | None:
	"""Map a former CRM label to a Shipment Type Link using master legacy_crm_labels."""
	label = (label or "").strip()
	if not label or not _shipment_type_field_queryable("legacy_crm_labels"):
		return None

	mode = (mode or "").strip()
	filters: dict = {}
	if _shipment_type_field_queryable("is_active"):
		filters["is_active"] = 1

	fields = ["name", "legacy_crm_labels", "default_mode_of_transport"]
	matches = []
	for row in frappe.get_all("Shipment Type", filters=filters, fields=fields):
		if label not in _parse_label_lines(row.get("legacy_crm_labels")):
			continue
		matches.append(row)

	if not matches:
		return None
	if mode:
		for row in matches:
			if (row.get("default_mode_of_transport") or "").strip() == mode:
				return row.name
	if len(matches) == 1:
		return matches[0].name
	return matches[0].name


def canonical_shipment_type_link(shipment_type: str | None, mode: str | None = None) -> str | None:
	"""Return the Shipment Type Link name from master (including legacy label resolution)."""
	st = (shipment_type or "").strip()
	if not st:
		return None
	row = get_shipment_type_record(st, mode=mode)
	if row:
		return row.get("name") or st
	resolved = resolve_shipment_type_from_legacy(st, mode)
	return resolved or st


def sync_mode_from_shipment_type(doc) -> None:
	"""Derive custom_mode_of_transport from the linked Shipment Type master."""
	if not doc.meta.has_field("custom_shipment_type"):
		return
	if not doc.meta.has_field("custom_mode_of_transport"):
		return
	st = doc.get("custom_shipment_type")
	mode = mode_from_master(st)
	if mode:
		doc.custom_mode_of_transport = mode


def copy_shipment_classification_from_source(target, source) -> None:
	"""Copy shipment type, mode, and container type from a preshipment source document."""
	if source.get("custom_shipment_type") and target.meta.has_field("custom_shipment_type"):
		mode = source.get("custom_mode_of_transport")
		link = canonical_shipment_type_link(source.get("custom_shipment_type"), mode)
		target.custom_shipment_type = link or source.get("custom_shipment_type")
	sync_mode_from_shipment_type(target)
	if not target.get("custom_mode_of_transport") and source.get("custom_mode_of_transport"):
		if target.meta.has_field("custom_mode_of_transport"):
			target.custom_mode_of_transport = source.get("custom_mode_of_transport")

	dest_container = get_cargo_type_field(target.meta)
	src_container = get_cargo_type_field(source.meta)
	if dest_container and src_container:
		value = source.get(src_container)
		if value not in (None, ""):
			target.set(dest_container, value)


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
	candidates = ["shipment_type_name", *_OPTIONAL_SHIPMENT_TYPE_FIELDS]
	fields = [f for f in candidates if _shipment_type_field_queryable(f)]
	# `name` is always a DB column but not reported by meta.has_field().
	return ["name", *fields]


def get_shipment_type_record(shipment_type: str | None, mode: str | None = None) -> dict | None:
	"""Load Shipment Type by Link name, shipment_type_name, or legacy CRM label."""
	st = (shipment_type or "").strip()
	if not st:
		return None

	fields = _shipment_type_query_fields()
	meta = _shipment_type_meta()

	if frappe.db.exists("Shipment Type", st):
		return frappe.db.get_value("Shipment Type", st, fields, as_dict=True)

	filters: dict = {"shipment_type_name": st}
	if meta and meta.has_field("is_active") and _shipment_type_field_queryable("is_active"):
		filters["is_active"] = 1

	row = frappe.db.get_value("Shipment Type", filters, fields, as_dict=True)
	if row:
		return row

	legacy_link = resolve_shipment_type_from_legacy(st, mode)
	if legacy_link and frappe.db.exists("Shipment Type", legacy_link):
		return frappe.db.get_value("Shipment Type", legacy_link, fields, as_dict=True)

	return None


def cgm_ref_prefix_from_master(shipment_type: str | None, mode: str | None = None) -> str | None:
	row = get_shipment_type_record(shipment_type, mode=mode)
	if row and row.get("cgm_ref_prefix"):
		return str(row.cgm_ref_prefix).strip().upper()
	return None


def _cargo_type_meta():
	if not frappe.db.exists("DocType", "Cargo Type"):
		return None
	return frappe.get_meta("Cargo Type")


def _cargo_type_field_queryable(fieldname: str) -> bool:
	meta = _cargo_type_meta()
	if not meta or not meta.has_field(fieldname):
		return False
	return frappe.db.has_column("Cargo Type", fieldname)


def get_cargo_type_record(cargo_type: str | None) -> dict | None:
	"""Load Cargo Type by Link name or cargo_type label."""
	ct = (cargo_type or "").strip()
	if not ct or not frappe.db.exists("DocType", "Cargo Type"):
		return None

	fields = ["name", "cargo_type"]
	if _cargo_type_field_queryable("cgm_ref_prefix"):
		fields.append("cgm_ref_prefix")

	if frappe.db.exists("Cargo Type", ct):
		return frappe.db.get_value("Cargo Type", ct, fields, as_dict=True)

	return frappe.db.get_value(
		"Cargo Type",
		{"cargo_type": ct},
		fields,
		as_dict=True,
	)


def cgm_ref_prefix_from_cargo_type(cargo_type: str | None) -> str | None:
	row = get_cargo_type_record(cargo_type)
	if row and row.get("cgm_ref_prefix"):
		return str(row.cgm_ref_prefix).strip().upper()
	return None


def container_tracking_mode_for_shipment_type(
	shipment_type: str | None, mode: str | None = None
) -> str | None:
	"""Container Tracker mode from Shipment Type master (container_tracker_mode or legacy field)."""
	row = get_shipment_type_record(shipment_type, mode=mode)
	if not row:
		return None
	if _shipment_type_field_queryable("container_tracker_mode") and row.get("container_tracker_mode"):
		return str(row.container_tracker_mode).strip()
	if _shipment_type_field_queryable("container_tracking_mode"):
		value = (row.get("container_tracking_mode") or "").strip()
		if value:
			return value
	return None


def get_task_template_for_shipment_type(shipment_type: str | None) -> str | None:
	"""CGM Task Template linked on Shipment Type."""
	row = get_shipment_type_record(shipment_type)
	if not row:
		return None
	if _shipment_type_field_queryable("task_template") and row.get("task_template"):
		return str(row.task_template).strip()
	return None


def get_task_flow_key_for_shipment_type(shipment_type: str | None) -> str | None:
	"""Task flow key from Shipment Type master (e.g. SEA_TRANSIT_IMPORT_E2E)."""
	row = get_shipment_type_record(shipment_type)
	if row and _shipment_type_field_queryable("task_flow_key"):
		value = (row.get("task_flow_key") or "").strip()
		if value:
			return value
	return None


def uses_container_tracking_for_shipment_type(shipment_type: str | None) -> bool:
	row = get_shipment_type_record(shipment_type)
	if not row:
		return False
	if _shipment_type_field_queryable("uses_container_tracking"):
		return bool(row.get("uses_container_tracking"))
	return False


def mode_from_master(shipment_type: str | None) -> str | None:
	row = get_shipment_type_record(shipment_type)
	if row and row.get("default_mode_of_transport"):
		return str(row.default_mode_of_transport).strip()
	return None


def transport_category_from_mode(mode: str | None) -> str | None:
	"""Map Mode of Transport label to UI category: sea, air, or road."""
	if not mode:
		return None
	key = str(mode).strip().lower()
	if key == "sea":
		return "sea"
	if key == "air":
		return "air"
	if key == "road":
		return "road"
	return None


def get_transport_category(shipment_type: str | None = None, mode: str | None = None) -> str | None:
	"""Resolve sea/air/road from Shipment Type master (preferred) or explicit mode."""
	mode_val = (mode or "").strip()
	row = get_shipment_type_record(shipment_type)
	if row and row.get("default_mode_of_transport"):
		mode_val = str(row.default_mode_of_transport).strip()
	return transport_category_from_mode(mode_val)


def shipment_type_profile(shipment_type: str | None) -> dict | None:
	"""Single Shipment Type row as a transport profile dict."""
	row = get_shipment_type_record(shipment_type)
	if not row:
		return None
	name = row.get("name") or shipment_type
	mode = mode_from_master(name) or (row.get("default_mode_of_transport") or "")
	profile = {
		"name": name,
		"shipment_type_name": row.get("shipment_type_name") or name,
		"default_mode_of_transport": mode,
		"category": get_transport_category(name, mode),
		"uses_unit_tracking": bool(row.get("uses_unit_tracking")),
	}
	if _shipment_type_field_queryable("container_tracker_mode") and row.get("container_tracker_mode"):
		profile["container_tracker_mode"] = row.get("container_tracker_mode")
	elif row.get("container_tracking_mode"):
		profile["container_tracking_mode"] = row.get("container_tracking_mode")
	if _shipment_type_field_queryable("task_template") and row.get("task_template"):
		profile["task_template"] = row.get("task_template")
	if _shipment_type_field_queryable("task_flow_key") and row.get("task_flow_key"):
		profile["task_flow_key"] = row.get("task_flow_key")
	if _shipment_type_field_queryable("uses_container_tracking"):
		profile["uses_container_tracking"] = bool(row.get("uses_container_tracking"))
	if _shipment_type_field_queryable("uses_transit_documents"):
		profile["uses_transit_documents"] = bool(row.get("uses_transit_documents"))
	if _shipment_type_field_queryable("uses_destination_entry"):
		profile["uses_destination_entry"] = bool(row.get("uses_destination_entry"))
	if _shipment_type_field_queryable("uses_export_documents"):
		profile["uses_export_documents"] = bool(row.get("uses_export_documents"))
	if _shipment_type_field_queryable("primary_transport_document"):
		profile["primary_transport_document"] = row.get("primary_transport_document") or "None"
	if _shipment_type_field_queryable("is_outbound"):
		profile["is_outbound"] = bool(row.get("is_outbound"))
	return profile


def apply_shipment_type_profile_to_doc(doc, shipment_type: str | None) -> bool:
	"""Set custom_shipment_type and custom_mode_of_transport from Shipment Type master."""
	if not shipment_type:
		return False
	link_name = canonical_shipment_type_link(shipment_type, doc.get("custom_mode_of_transport"))
	if not link_name:
		return False
	changed = False
	if doc.meta.has_field("custom_shipment_type") and doc.get("custom_shipment_type") != link_name:
		doc.set("custom_shipment_type", link_name)
		changed = True
	sync_mode_from_shipment_type(doc)
	return changed or bool(doc.has_value_changed("custom_mode_of_transport"))


def get_cargo_type_field(meta) -> str | None:
	"""Return the container-type Link field on Opportunity, Project, or Lead."""
	for fieldname in ("custom_cargo_type", "custom_cargo_type_"):
		if meta.has_field(fieldname):
			return fieldname
	return None


def get_opportunity_cargo_type_field(meta=None) -> str | None:
	"""Backward-compatible alias for get_cargo_type_field on Opportunity."""
	return get_cargo_type_field(meta or frappe.get_meta("Opportunity"))


def sync_cargo_type_from_linked_bl(doc) -> None:
	"""Keep container type aligned with the linked Bill of Lading."""
	container_field = get_cargo_type_field(doc.meta)
	if not container_field:
		return

	bl_field = _bill_of_lading_link_field(doc)
	if not bl_field:
		return

	bl_name = doc.get(bl_field)
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return

	cargo_type = frappe.db.get_value("Bill of Lading", bl_name, "cargo_type")
	if cargo_type and doc.get(container_field) != cargo_type:
		doc.set(container_field, cargo_type)


def _bill_of_lading_link_field(doc) -> str | None:
	config = get_bl_config()
	candidate = config.get("opportunity_bl_field")
	if candidate and doc.meta.has_field(candidate):
		return candidate
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import get_link_field_for_doctype

	return get_link_field_for_doctype(doc.doctype, "Bill of Lading")


def apply_bl_classification_to_doc(target_doc, bl_doc) -> bool:
	"""Copy shipment type, derived mode, and container type from Bill of Lading."""
	changed = False
	if apply_shipment_type_profile_to_doc(target_doc, bl_doc.get("shipment_type")):
		changed = True
	cargo_type = bl_doc.get("cargo_type")
	container_field = get_cargo_type_field(target_doc.meta)
	if cargo_type and container_field and target_doc.get(container_field) != cargo_type:
		target_doc.set(container_field, cargo_type)
		changed = True
	return changed


BL_TO_OPPORTUNITY_TRACKING_FIELDS = (
	("client_refrence_no", "custom_client_refrence_no"),
	("batch_no", "custom_batch_no"),
)

# Confirmed shipment fields — keep Opportunity as the latest source of truth.
BL_TO_OPPORTUNITY_SHIPPING_FIELDS = (
	("shipping_line", "custom_shipping_line"),
	("vessel", "custom_vessel"),
	("etd", "custom_etd"),
	("eta", "custom_eta"),
	("port_of_loading", "custom_port_of_loading"),
	("port_of_discharge", "custom_port_of_discharge"),
	("voyage_number", "custom_voyage_number"),
	("gross_weight", "custom_gross_weight"),
	("net_weight", "custom_net_weight"),
	("weight_uom", "custom_weight_uom_"),
)

BL_TO_OPPORTUNITY_DETAIL_FIELDS = (
	("commodity", "custom_description_of_goods"),
	("bl_number", "custom_draft_bl_number"),
	("number_of_packages", "custom_number_of_packages"),
	("package_type", "custom_package_type"),
)

# Air Waybill → Opportunity / Project scalar mappings.
AWB_TO_OPPORTUNITY_FIELDS = (
	("client_reference_no", "custom_client_refrence_no"),
	("description", "custom_description_of_goods"),
	("airline", "custom_airline"),
	("eta", "custom_eta"),
	("etd", "custom_etd"),
	("weight_uom", "custom_weight_uom_"),
	("net_weight", "custom_net_weight"),
	("gross_weight", "custom_gross_weight"),
	("port_of_loading", "custom_port_of_loading"),
	("port_of_discharge", "custom_port_of_discharge"),
)

OPPORTUNITY_TO_AWB_FIELDS = tuple(
	(opp_field, awb_field) for awb_field, opp_field in AWB_TO_OPPORTUNITY_FIELDS
)

OPPORTUNITY_TO_PROJECT_TRACKING_FIELDS = (
	("custom_client_refrence_no", "custom_client_refrence_no"),
	("custom_batch_no", "custom_batch_no"),
)

OPPORTUNITY_TO_PROJECT_CARRIER_FIELDS = (
	("custom_vessel", "custom_vessel"),
	("custom_airline", "custom_airline"),
)


def copy_carrier_fields_from_source(target, source) -> None:
	"""Copy vessel and/or airline onto Project when filled on the preshipment source."""
	for src_field, dest_field in OPPORTUNITY_TO_PROJECT_CARRIER_FIELDS:
		if not target.meta.has_field(dest_field) or not source.meta.has_field(src_field):
			continue
		value = source.get(src_field)
		if value not in (None, "") and not target.get(dest_field):
			target.set(dest_field, value)


def _bl_batch_number_value(bl_doc) -> str | None:
	batch = (bl_doc.get("batch_no") or "").strip()
	if batch:
		return batch
	from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
		parse_batch_number_from_bl_name,
	)

	parsed = parse_batch_number_from_bl_name(bl_doc.name)
	return str(parsed) if parsed else None


def bl_tracking_payload(bl_doc) -> dict:
	"""Client ref and batch from Bill of Lading (vessel/ETA/ATA/CGM ref are Project-only)."""
	return {
		"client_refrence_no": bl_doc.get("client_refrence_no"),
		"batch_no": _bl_batch_number_value(bl_doc),
	}


def apply_bl_tracking_fields_to_doc(target_doc, bl_doc) -> bool:
	"""Copy client ref and batch from Bill of Lading onto Opportunity."""
	changed = False
	values = bl_tracking_payload(bl_doc)
	for src_field, dest_field in BL_TO_OPPORTUNITY_TRACKING_FIELDS:
		if not target_doc.meta.has_field(dest_field):
			continue
		value = values.get(src_field)
		if value in (None, ""):
			continue
		if target_doc.get(dest_field) != value:
			target_doc.set(dest_field, value)
			changed = True
	return changed


def _set_doc_field_if_changed(target_doc, fieldname: str, value) -> bool:
	"""Set a field when the source value is present and differs. Returns True if changed."""
	if not fieldname or not target_doc.meta.has_field(fieldname):
		return False
	if value in (None, ""):
		return False

	df = target_doc.meta.get_field(fieldname)
	if df and df.fieldtype in ("Float", "Currency", "Percent", "Int"):
		try:
			value = float(str(value).replace(",", "").strip())
		except (TypeError, ValueError):
			return False
		if df.fieldtype == "Int":
			value = int(value)

	if target_doc.get(fieldname) == value:
		return False
	target_doc.set(fieldname, value)
	return True


def apply_bl_detail_fields_to_doc(target_doc, bl_doc) -> bool:
	"""Copy descriptive BL fields onto Opportunity after primary document submit."""
	changed = False
	for src_field, dest_field in BL_TO_OPPORTUNITY_DETAIL_FIELDS:
		if _set_doc_field_if_changed(target_doc, dest_field, bl_doc.get(src_field)):
			changed = True
	return changed


def apply_bl_shipping_fields_to_doc(target_doc, bl_doc) -> bool:
	"""Copy confirmed shipping / cargo scalars from Bill of Lading onto Opportunity/Project."""
	changed = False
	for src_field, dest_field in BL_TO_OPPORTUNITY_SHIPPING_FIELDS:
		if _set_doc_field_if_changed(target_doc, dest_field, bl_doc.get(src_field)):
			changed = True

	# Project fieldnames differ slightly from Opportunity (weight_uom / net_weight / ETD).
	alternates = (
		("net_weight", "custom_net_weight"),
		("weight_uom", "custom_weight_uom"),
		("gross_weight", "custom_gross_weight"),
		("etd", "custom_expected_time_of_depatureetd"),
	)
	for src_field, dest_field in alternates:
		if _set_doc_field_if_changed(target_doc, dest_field, bl_doc.get(src_field)):
			changed = True
	return changed


def apply_bl_fields_to_doc(target_doc, bl_doc) -> bool:
	"""Copy shipment classification, shipping, tracking, and detail fields from Bill of Lading."""
	classification_changed = apply_bl_classification_to_doc(target_doc, bl_doc)
	shipping_changed = apply_bl_shipping_fields_to_doc(target_doc, bl_doc)
	tracking_changed = apply_bl_tracking_fields_to_doc(target_doc, bl_doc)
	detail_changed = apply_bl_detail_fields_to_doc(target_doc, bl_doc)
	return classification_changed or shipping_changed or tracking_changed or detail_changed


def apply_awb_scalar_fields_to_doc(target_doc, awb_doc) -> bool:
	"""Copy Air Waybill scalars onto Opportunity or Project."""
	changed = False
	for src_field, dest_field in AWB_TO_OPPORTUNITY_FIELDS:
		if _set_doc_field_if_changed(target_doc, dest_field, awb_doc.get(src_field)):
			changed = True
	# Project form shows custom_expected_time_of_depatureetd (custom_etd is hidden).
	alternates = (
		("net_weight", "custom_net_weight"),
		("weight_uom", "custom_weight_uom"),
		("gross_weight", "custom_gross_weight"),
		("etd", "custom_expected_time_of_depatureetd"),
	)
	for src_field, dest_field in alternates:
		if _set_doc_field_if_changed(target_doc, dest_field, awb_doc.get(src_field)):
			changed = True
	return changed


def apply_awb_fields_to_doc(target_doc, awb_doc) -> bool:
	"""Copy shipment type, mode, and scalar fields from Air Waybill."""
	classification_changed = apply_shipment_type_profile_to_doc(
		target_doc, awb_doc.get("shipment_type")
	)
	if (
		target_doc.meta.has_field("custom_mode_of_transport")
		and not target_doc.get("custom_mode_of_transport")
		and _set_doc_field_if_changed(target_doc, "custom_mode_of_transport", "Air")
	):
		classification_changed = True
	scalar_changed = apply_awb_scalar_fields_to_doc(target_doc, awb_doc)
	return classification_changed or scalar_changed


def awb_propagation_payload(awb_doc) -> dict:
	"""Air Waybill fields for client-side Opportunity apply and API responses."""
	shipment_type = awb_doc.get("shipment_type")
	link_name = canonical_shipment_type_link(shipment_type) if shipment_type else None
	profile = shipment_type_profile(link_name or shipment_type) if shipment_type else None
	payload = {
		"awb_name": awb_doc.name,
		"shipment_type": link_name or shipment_type,
		"default_mode_of_transport": (profile or {}).get("default_mode_of_transport") or "Air",
	}
	for src_field, dest_field in AWB_TO_OPPORTUNITY_FIELDS:
		value = awb_doc.get(src_field)
		if value not in (None, ""):
			payload[dest_field] = value
			payload[src_field] = value
	return payload


def bl_classification_payload(bl_doc) -> dict:
	"""Shipment classification fields from a Bill of Lading for client-side apply."""
	shipment_type = bl_doc.get("shipment_type")
	link_name = canonical_shipment_type_link(shipment_type) if shipment_type else None
	profile = shipment_type_profile(link_name or shipment_type) if shipment_type else None
	return {
		"shipment_type": link_name or shipment_type,
		"default_mode_of_transport": (profile or {}).get("default_mode_of_transport"),
		"cargo_type": bl_doc.get("cargo_type"),
	}


def bl_propagation_payload(bl_doc) -> dict:
	"""Classification + shipping + tracking fields from Bill of Lading for API responses."""
	payload = {**bl_classification_payload(bl_doc), **bl_tracking_payload(bl_doc)}
	for src_field, dest_field in (
		*BL_TO_OPPORTUNITY_SHIPPING_FIELDS,
		*BL_TO_OPPORTUNITY_DETAIL_FIELDS,
	):
		value = bl_doc.get(src_field)
		if value not in (None, ""):
			payload[dest_field] = value
			# Also expose source names for client helpers that read BL field names.
			payload[src_field] = value
	return payload


def copy_tracking_fields_from_source(target, source) -> None:
	"""Copy client ref and batch from Opportunity onto Project."""
	for src_field, dest_field in OPPORTUNITY_TO_PROJECT_TRACKING_FIELDS:
		if not target.meta.has_field(dest_field) or not source.meta.has_field(src_field):
			continue
		value = source.get(src_field)
		if value not in (None, ""):
			target.set(dest_field, value)


def is_sea_import_enabled(shipment_type: str | None) -> bool:
	"""True when Shipment Type uses the sea import task template (or legacy flow key)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		SEA_IMPORT_TEMPLATE,
		SEA_TRANSIT_IMPORT_TEMPLATE,
		normalize_template_name,
	)

	template = get_task_template_for_shipment_type(shipment_type)
	if template:
		normalized = normalize_template_name(template)
		return normalized in (SEA_IMPORT_TEMPLATE, SEA_TRANSIT_IMPORT_TEMPLATE)

	flow = get_task_flow_key_for_shipment_type(shipment_type)
	normalized = normalize_template_name(flow)
	return normalized in (SEA_IMPORT_TEMPLATE, SEA_TRANSIT_IMPORT_TEMPLATE)


def sea_import_enabled_for_project(project) -> bool:
	"""Project uses sea-import automation (UCR gates, workflow) from its Shipment Type."""
	shipment_type = project.get("custom_shipment_type") if hasattr(project, "get") else None
	if shipment_type:
		return is_sea_import_enabled(shipment_type)
	mode = project.get("custom_mode_of_transport") if hasattr(project, "get") else None
	return get_transport_category(None, mode) == "sea"

# ─── Legacy CGM reference (old project names) ────────────────────────────────
# New Projects use Client Ref / Quantity[/ Batch] via project_naming.py.

LEGACY_CGM_REF_PATTERN = re.compile(r"^CGM/[A-Z]{2,5}\d{3}/\d{4}$", re.IGNORECASE)


def is_cgm_ref(value: str | None) -> bool:
	"""True for legacy CGM/FCL001/0626-style references."""
	if not value:
		return False
	return bool(LEGACY_CGM_REF_PATTERN.match(str(value).strip().upper()))


# ─── Project Field Helpers ────────────────────────────────────────────────────


def apply_shipment_data(project, shipment_type=None, mode=None):
	"""Set shipment classification; derive mode from Shipment Type master when known."""
	if shipment_type:
		link = canonical_shipment_type_link(
			shipment_type,
			mode or project.get("custom_mode_of_transport"),
		)
		project.custom_shipment_type = link or shipment_type
	if mode and project.meta.has_field("custom_mode_of_transport"):
		project.custom_mode_of_transport = mode

	sync_mode_from_shipment_type(project)

	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_shipment_status"):
		project.custom_shipment_status = "Draft"


def normalize_shipment_classification(shipment_type=None, mode=None):
	"""
	Return (shipment_type_link, mode) using Shipment Type master only.

	Legacy CRM labels are resolved via each record's legacy_crm_labels field.
	"""
	st = (shipment_type or "").strip()
	m = (mode or "").strip()
	row = get_shipment_type_record(st, mode=m)
	if row:
		link_name = row.get("name") or st
		return link_name, mode_from_master(link_name) or m
	return st or None, m or None


def normalize_shipment_fields_on_doc(doc) -> None:
	"""Resolve shipment type Link + mode from Shipment Type master configuration."""
	if not doc.meta.has_field("custom_shipment_type"):
		return

	mode = doc.get("custom_mode_of_transport") if doc.meta.has_field("custom_mode_of_transport") else None
	normalized_type, derived_mode = normalize_shipment_classification(
		doc.get("custom_shipment_type"),
		mode,
	)
	if normalized_type:
		doc.custom_shipment_type = normalized_type
	if derived_mode and doc.meta.has_field("custom_mode_of_transport"):
		doc.custom_mode_of_transport = derived_mode


# ==================== Bill of Lading sync ====================

"""Container utilities shared across Bill of Lading, Opportunity, Lead and Project.

Bill of Lading–specific logic (Opportunity sync, submit payload, opportunity
creation) lives on the controller in
``doctype.bill_of_lading.bill_of_lading``.
"""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import get_bl_config

def get_container_fields() -> list[str]:
	"""Dynamically fetch relevant fields from Container DocType."""
	skip_types = {
		"Section Break",
		"Column Break",
		"Tab Break",
		"HTML",
		"Button",
		"Heading",
	}
	return [
		field.fieldname
		for field in frappe.get_meta("Container").fields
		if field.fieldtype not in skip_types and not field.hidden
	]


def container_row_cargo_size(row) -> str:
	"""Cargo size from a Container child row (supports legacy type_of_container)."""
	if isinstance(row, dict):
		return (row.get("cargo_size") or row.get("type_of_container") or "").strip()
	return (getattr(row, "cargo_size", None) or getattr(row, "type_of_container", None) or "").strip()


def tracker_cargo_size_field() -> str:
	"""Container Tracker field storing physical size (20FT / 45FT)."""
	meta = frappe.get_meta("Container Tracker")
	for fieldname in ("cargo_size", "cargo_type", "type_of_container"):
		if meta.has_field(fieldname):
			return fieldname
	return "cargo_size"


def tracker_row_cargo_size(row) -> str:
	"""Cargo size from a Container Tracker row or document."""
	fieldname = tracker_cargo_size_field()
	if isinstance(row, dict):
		return (row.get(fieldname) or row.get("cargo_size") or row.get("cargo_type") or row.get("type_of_container") or "").strip()
	return (
		getattr(row, fieldname, None)
		or getattr(row, "cargo_size", None)
		or getattr(row, "cargo_type", None)
		or getattr(row, "type_of_container", None)
		or ""
	).strip()


def resolve_cargo_size_link(value: str | None) -> str | None:
	"""Ensure Cargo Size master exists and return a valid link name."""
	raw = (value or "").strip()
	if not raw:
		return None
	if not frappe.db.exists("DocType", "Cargo Size"):
		return raw

	if frappe.db.exists("Cargo Size", raw):
		return raw

	by_field = frappe.db.get_value("Cargo Size", {"cargo_size": raw}, "name")
	if by_field:
		return by_field

	normalized = raw.upper().replace(" ", "")
	for row in frappe.get_all("Cargo Size", fields=["name", "cargo_size"]):
		label = (row.get("cargo_size") or row.get("name") or "").upper().replace(" ", "")
		if label == normalized:
			return row.name

	doc = frappe.get_doc({"doctype": "Cargo Size", "cargo_size": raw})
	doc.insert(ignore_permissions=True)
	return doc.name


def normalize_container_row(row: dict) -> dict:
	"""Return container child row values safe for Link validation."""
	values = {field: row.get(field) or "" for field in get_container_fields()}
	legacy_size = (row.get("type_of_container") or "").strip()
	if not values.get("cargo_size") and legacy_size:
		values["cargo_size"] = legacy_size
	if values.get("cargo_size"):
		values["cargo_size"] = resolve_cargo_size_link(values["cargo_size"]) or ""
	# Tracker fields are populated on Project, not copied from BL intake rows.
	for fieldname in ("container_tracker", "status", "demurrage_days"):
		values[fieldname] = ""
	return values

def get_cargo_type_order() -> list[str]:
	"""Pull cargo types from Cargo Type DocType ordered by idx."""
	return frappe.get_all(
		"Cargo Type",
		fields=["cargo_type"],
		order_by="idx asc",
		pluck="cargo_type",
	)

def get_bl_quantity_summary(bl_doc) -> str:
	"""Return container quantity summary for a Bill of Lading document."""
	summary_field = "container_summary"
	if bl_doc.meta.has_field(summary_field) and bl_doc.get(summary_field):
		return bl_doc.get(summary_field)
	from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
		summarize_bl_container_quantities,
	)
	return summarize_bl_container_quantities(bl_doc.name)

# ─── Container row fetching ───────────────────────────────────────────────────
def fetch_container_rows(bill_of_lading: str | None) -> list[dict]:
	if not bill_of_lading or not frappe.db.exists("Bill of Lading", bill_of_lading):
		return []
	return [
		normalize_container_row(row)
		for row in frappe.get_all(
			"Container",
			filters={"parent": bill_of_lading, "parenttype": "Bill of Lading"},
			fields=get_container_fields(),
			order_by="idx asc",
		)
	]

def resolve_bill_of_lading_name(attachment: str) -> str | None:
	"""Resolve a Bill of Lading name from its docname or attachment file path."""
	if not attachment:
		return None
	if frappe.db.exists("Bill of Lading", attachment):
		return attachment

	attachment_field = get_bl_config().get("attachment_field")
	if not attachment_field:
		return None
	return frappe.db.get_value("Bill of Lading", {attachment_field: attachment}, "name")


def resolve_bl_name_from_preshipment(source_doc) -> str | None:
	"""Resolve Bill of Lading from link field, client documents, or back-link on BL."""
	if not source_doc:
		return None

	config = get_bl_config()
	bl_field = config.get("opportunity_bl_field")
	if bl_field and source_doc.meta.has_field(bl_field):
		bl_name = source_doc.get(bl_field)
		if bl_name and frappe.db.exists("Bill of Lading", bl_name):
			return bl_name

	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		document_types_match,
		get_document_type_link_name,
		get_opportunity_documents_field,
		primary_attachment,
	)

	clients_field = get_opportunity_documents_field()
	if clients_field and source_doc.meta.has_field(clients_field):
		bl_type = get_document_type_link_name("BL")
		if bl_type:
			for row in source_doc.get(clients_field) or []:
				if not document_types_match(row.document_type, bl_type):
					continue
				file_ref = primary_attachment(row)
				if not file_ref:
					continue
				bl_name = resolve_bill_of_lading_name(file_ref)
				if bl_name:
					return bl_name

	source_field = config.get("opportunity_source_field")
	if source_field and source_doc.name:
		bl_name = frappe.db.get_value(
			"Bill of Lading",
			{source_field: source_doc.name, "docstatus": 1},
			"name",
			order_by="modified desc",
		)
		if bl_name:
			return bl_name
	return None


# ─── Preshipment container sync (Opportunity / Lead / Project) ─────────────────
def sync_opportunity_bl_from_clients_documents(doc, method=None) -> None:
	"""Link Bill of Lading from Clients Documents BL attachment when the link field is empty."""
	if doc.doctype != "Opportunity":
		return

	config = get_bl_config()
	bl_field = config.get("opportunity_bl_field")
	quantity_field = config.get("opportunity_quantity_field")
	if not bl_field or doc.get(bl_field):
		return

	bl_name = resolve_bl_name_from_preshipment(doc)
	if not bl_name:
		return

	doc.set(bl_field, bl_name)
	if quantity_field and doc.meta.has_field(quantity_field) and not doc.get(quantity_field):
		bl_doc = frappe.get_doc("Bill of Lading", bl_name)
		doc.set(quantity_field, get_bl_quantity_summary(bl_doc))


def sync_preshipment_containers_from_bl(doc, method=None) -> None:
	"""Populate container rows and BL tracking fields from the linked Bill of Lading."""
	config = get_bl_config()
	bl_field = config.get("opportunity_bl_field")
	container_field = config.get("opportunity_container_field")

	sync_cargo_type_from_linked_bl(doc)

	bl_name = doc.get(bl_field) if bl_field else None
	if bl_name and frappe.db.exists("Bill of Lading", bl_name):
		bl_doc = frappe.get_doc("Bill of Lading", bl_name)
		apply_bl_fields_to_doc(doc, bl_doc)

	if not bl_field or not container_field:
		return
	if not doc.meta.has_field(container_field):
		return

	rows = fetch_container_rows(bl_name) if bl_name else []

	doc.set(container_field, [])
	for row in rows:
		doc.append(container_field, normalize_container_row(row))

def apply_bill_of_lading_from_source(target_doc, source_doc) -> None:
	"""Copy Bill of Lading link and container rows from source onto target doc."""
	config = get_bl_config()
	bl_field = config.get("opportunity_bl_field")

	if not bl_field or not source_doc or not target_doc.meta.has_field(bl_field):
		return

	bl_name = resolve_bl_name_from_preshipment(source_doc)
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return

	target_doc.set(bl_field, bl_name)
	sync_preshipment_containers_from_bl(target_doc)

	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		carry_bill_of_lading_attachment_to_project,
	)

	carry_bill_of_lading_attachment_to_project(
		target_doc, bl_name=bl_name, source_doc=source_doc
	)

# ─── Whitelisted API methods ──────────────────────────────────────────────────
@frappe.whitelist()
def get_bl_container_select_options(bill_of_lading: str | None = None) -> list[dict]:
	if not bill_of_lading or not frappe.db.exists("Bill of Lading", bill_of_lading):
		return []
	frappe.has_permission("Bill of Lading", ptype="read", doc=bill_of_lading, throw=True)
	rows = fetch_container_rows(bill_of_lading)

	options = []
	for row in rows:
		number = (row.get("container_number") or "").strip()
		if not number:
			continue
		parts = [number]
		if row.get("cargo_size"):
			parts.append(str(row.get("cargo_size")))
		if row.get("seal_no"):
			parts.append(f"Seal {row.seal_no}")
		options.append({"value": number, "label": " - ".join(parts)})
	return options

@frappe.whitelist()
def get_containers_for_bl_attachment(attachment: str, opportunity: str = None) -> dict:
	"""
	Given a Bill of Lading name or file attachment path, return
	container rows, quantity and attachment in a single response.
	"""
	if not attachment:
		return {"containers": [], "quantity": "", "attachment": ""}

	bl_name = resolve_bill_of_lading_name(attachment)
	if not bl_name:
		frappe.msgprint(
			f"No Bill of Lading found for: {attachment}",
			indicator="orange",
			alert=True,
		)
		return {"containers": [], "quantity": "", "attachment": ""}

	frappe.has_permission("Bill of Lading", ptype="read", doc=bl_name, throw=True)

	bl_doc = frappe.get_doc("Bill of Lading", bl_name)
	attachment_field = get_bl_config().get("attachment_field")

	return {
		"bl_name": bl_name,
		"containers": fetch_container_rows(bl_name),
		"quantity": get_bl_quantity_summary(bl_doc),
		"attachment": bl_doc.get(attachment_field) or "" if attachment_field else "",
		**bl_propagation_payload(bl_doc),
	}


@frappe.whitelist()
def get_shipment_type_profiles() -> dict:
	"""Active Shipment Type master rows keyed by name (source of truth for client UI)."""
	if not frappe.db.exists("DocType", "Shipment Type"):
		return {}

	fields = ["name", "shipment_type_name", "default_mode_of_transport"]
	for optional in (
		"task_template",
		"uses_unit_tracking",
		"uses_container_tracking",
		"uses_transit_documents",
		"uses_destination_entry",
		"uses_export_documents",
		"primary_transport_document",
		"is_outbound",
		"task_flow_key",
		"container_tracker_mode",
		"requires_bill_of_lading",
		"requires_air_waybill",
		"container_tracking_mode",
		"legacy_crm_labels",
		"is_active",
	):
		if _shipment_type_field_queryable(optional):
			fields.append(optional)

	filters = {}
	if _shipment_type_field_queryable("is_active"):
		filters["is_active"] = 1

	profiles: dict[str, dict] = {}
	for row in frappe.get_all("Shipment Type", filters=filters, fields=fields, order_by="name asc"):
		name = row.name
		mode = (row.get("default_mode_of_transport") or "").strip()
		profile = {
			"shipment_type_name": row.get("shipment_type_name") or name,
			"default_mode_of_transport": mode,
			"category": transport_category_from_mode(mode),
			"uses_unit_tracking": bool(row.get("uses_unit_tracking")),
			"requires_bill_of_lading": bool(row.get("requires_bill_of_lading")),
			"requires_air_waybill": bool(row.get("requires_air_waybill")),
		}
		if row.get("task_template"):
			profile["task_template"] = row.get("task_template")
		if row.get("container_tracker_mode"):
			profile["container_tracker_mode"] = row.get("container_tracker_mode")
		elif row.get("container_tracking_mode"):
			profile["container_tracking_mode"] = row.get("container_tracking_mode")
		if row.get("task_flow_key"):
			profile["task_flow_key"] = row.get("task_flow_key")
		if _shipment_type_field_queryable("uses_container_tracking"):
			profile["uses_container_tracking"] = bool(row.get("uses_container_tracking"))
		if _shipment_type_field_queryable("uses_transit_documents"):
			profile["uses_transit_documents"] = bool(row.get("uses_transit_documents"))
		if _shipment_type_field_queryable("uses_destination_entry"):
			profile["uses_destination_entry"] = bool(row.get("uses_destination_entry"))
		if _shipment_type_field_queryable("uses_export_documents"):
			profile["uses_export_documents"] = bool(row.get("uses_export_documents"))
		if _shipment_type_field_queryable("primary_transport_document"):
			profile["primary_transport_document"] = row.get("primary_transport_document") or "None"
		if _shipment_type_field_queryable("is_outbound"):
			profile["is_outbound"] = bool(row.get("is_outbound"))
		profiles[name] = profile
		if _shipment_type_field_queryable("legacy_crm_labels"):
			for label in _parse_label_lines(row.get("legacy_crm_labels")):
				if label and label not in profiles:
					profiles[label] = profile
	return profiles

@frappe.whitelist()
def get_container_rows_for_bill_of_lading(bill_of_lading: str | None = None) -> list[dict]:
	if not bill_of_lading:
		return []
	if not frappe.db.exists("Bill of Lading", bill_of_lading):
		return []
	frappe.has_permission("Bill of Lading", ptype="read", doc=bill_of_lading, throw=True)
	return fetch_container_rows(bill_of_lading)


# ==================== Customer / Opportunity hooks ====================

"""Customer hooks - sync onboarding attachments to linked Projects."""


def on_customer_update(doc, _method=None):
	if doc.is_new():
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import CUSTOMER_ATTACH_TO_DOCUMENT_CODE
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import refresh_projects_for_customer

	# Re-sync projects when a mapped onboarding attachment changes.
	if not any(
		doc.has_value_changed(fieldname)
		for fieldname in CUSTOMER_ATTACH_TO_DOCUMENT_CODE
		if doc.meta.has_field(fieldname)
	):
		return

	refresh_projects_for_customer(doc.name)


# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Opportunity server-side customizations."""

import frappe
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	APPROVED_WORKFLOW_STATE,
	BACK_LINKED_DOCTYPES,
	OPPORTUNITY_TRANSPORT_BACK_LINK_FIELD,
)


def clear_back_links_on_trash(doc, method=None) -> None:
	for doctype in BACK_LINKED_DOCTYPES:
		for name in frappe.get_all(
			doctype, filters={"linked_opportunity": doc.name}, pluck="name"
		):
			frappe.db.set_value(
				doctype, name, "linked_opportunity", None, update_modified=False
			)


def stamp_verified_documents_on_approval(doc, method=None) -> None:
	"""Stamp Verified By / Verified On on the document rows once the Opportunity
	is Approved in its workflow. Only fills rows not yet verified, so re-saving an
	already-approved Opportunity does not churn the values."""
	if doc.get("workflow_state") != APPROVED_WORKFLOW_STATE:
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		get_opportunity_documents_field,
	)

	field = get_opportunity_documents_field()
	if not field or not doc.meta.has_field(field):
		return

	for row in doc.get(field) or []:
		if not row.verified_by:
			row.verified_by = frappe.session.user
		if not row.verified_on:
			row.verified_on = now_datetime()
		if row.meta.has_field("status"):
			row.status = "Verified"


# ─── Connections (form dashboard) ─────────────────────────────────────────────
def get_dashboard_data(data):
	"""Tailor the Opportunity "Connections" for the shipping workflow.

	ERPNext ships Quotation / Request for Quotation / Supplier Quotation. For CGM
	the Opportunity branches into a Bill of Lading / Air Waybill and a (shipment)
	Project, so we keep Quotation, drop the two procurement quotations, and surface
	those shipping links instead.
	"""
	data["transactions"] = [
		{"label": "Quotation", "items": ["Quotation"]},
		{"label": "Shipment", "items": list(BACK_LINKED_DOCTYPES)},
		{"label": "Project", "items": ["Project"]},
	]
	non_standard = data.setdefault("non_standard_fieldnames", {})
	for doctype in BACK_LINKED_DOCTYPES:
		non_standard[doctype] = OPPORTUNITY_TRANSPORT_BACK_LINK_FIELD
	non_standard["Project"] = "custom_source_opportunity"

	return data


# ─── BL / AWB configuration (from former utils.py) ───────────────────────────


def get_bl_container_child_field() -> str | None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
		get_container_table_field_for_doctype,
	)
	return get_container_table_field_for_doctype("Bill of Lading")


def get_awb_value_from_doc(doc) -> str | None:
	"""Return the first non-empty AWB-style field value on a document."""
	for field in doc.meta.fields:
		if field.fieldtype not in ("Data", "Link", "Small Text"):
			continue
		name = field.fieldname.lower()
		if not any(token in name for token in ("awb", "airway", "air_waybill")):
			continue
		value = doc.get(field.fieldname)
		if value not in (None, ""):
			return value
	return None


def get_project_awb_field() -> str | None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import get_field_from_meta
	return get_field_from_meta("Project", "awb_number") or get_field_from_meta("Project", "awb")
