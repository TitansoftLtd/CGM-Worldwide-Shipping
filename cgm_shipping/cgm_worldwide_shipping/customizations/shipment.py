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
	candidates = ["name", "shipment_type_name", "cgm_ref_prefix", *_OPTIONAL_SHIPMENT_TYPE_FIELDS]
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

# ─── CGM reference / Project Name ─────────────────────────────────────────────
# Tracking sheet format: CGM/FCL001/1022  (prefix + 3-digit seq + MMYY period)


CGM_REF_PATTERN = re.compile(r"^CGM/[A-Z]{2,5}\d{3}/\d{4}$")


def is_cgm_ref(value: str | None) -> bool:
	if not value:
		return False
	return bool(CGM_REF_PATTERN.match(str(value).strip().upper()))


def cgm_ref_prefix(shipment_type=None, mode=None) -> str:
	"""Map shipment classification to tracking-sheet prefix (FCL, LCL, IM, …)."""
	st = (shipment_type or "").strip()
	prefix = cgm_ref_prefix_from_master(st, mode)
	if prefix:
		return prefix

	mode = (mode or "").strip()
	if st == "Import":
		if mode == "Sea":
			return "FCL"
		if mode == "Air":
			return "AIR"
		if mode == "Road":
			return "ROD"
		return "IM"
	if st == "Export":
		return "EX"
	if mode == "Sea":
		return "FCL"
	if mode == "Air":
		return "AIR"
	if mode == "Road":
		return "ROD"
	return "IM"


def _next_cgm_ref_sequence(prefix: str, period: str) -> int:
	"""Next 3-digit sequence for CGM/{prefix}NNN/{period} in this calendar month."""
	like = f"CGM/{prefix}%/{period}"
	rows = frappe.db.sql(
		"""
		SELECT project_name AS ref FROM `tabProject` WHERE UPPER(project_name) LIKE %s
		UNION
		SELECT custom_cgm_ref_no AS ref FROM `tabProject`
		WHERE custom_cgm_ref_no IS NOT NULL AND custom_cgm_ref_no != ''
		  AND UPPER(custom_cgm_ref_no) LIKE %s
		""",
		(like.upper(), like.upper()),
		as_dict=True,
	)
	seq_pattern = re.compile(rf"^CGM/{re.escape(prefix)}(\d{{3}})/{re.escape(period)}$")
	max_seq = 0
	for row in rows:
		ref = (row.ref or "").strip().upper()
		match = seq_pattern.match(ref)
		if match:
			max_seq = max(max_seq, int(match.group(1)))
	return max_seq + 1


def _cgm_ref_in_use(ref: str) -> bool:
	"""True if a Project already uses this reference as its name or CGM ref."""
	return bool(
		frappe.db.exists("Project", {"project_name": ref})
		or frappe.db.exists("Project", {"custom_cgm_ref_no": ref})
	)


def build_cgm_ref_no(shipment_type=None, mode=None, opened_date=None) -> str:
	"""Allocate CGM/LCL001/1022-style reference for the shipment tracking sheet.

	Collisions are guarded two ways: this checks both project_name and
	custom_cgm_ref_no when allocating, and patch v2_39 adds a unique index on
	custom_cgm_ref_no so a concurrent race fails loudly at insert (surfaced as a
	retryable message in insert_shipment_project) instead of silently duplicating.
	"""
	prefix = cgm_ref_prefix(shipment_type, mode)
	dt = getdate(opened_date or today())
	period = dt.strftime("%m%y")
	seq = _next_cgm_ref_sequence(prefix, period)
	for candidate_seq in range(seq, seq + 1000):
		ref = f"CGM/{prefix}{candidate_seq:03d}/{period}"
		if not _cgm_ref_in_use(ref):
			return ref
	frappe.throw("Could not allocate a unique CGM reference number.")


def assign_cgm_project_reference(project) -> None:
	"""Set project_name and custom_cgm_ref_no to the tracking-sheet CGM reference."""
	if project.get("custom_cgm_ref_no") and is_cgm_ref(project.custom_cgm_ref_no):
		if not is_cgm_ref(project.project_name):
			project.project_name = project.custom_cgm_ref_no
		return

	if project.project_name and is_cgm_ref(project.project_name):
		if project.meta.has_field("custom_cgm_ref_no") and not project.get("custom_cgm_ref_no"):
			project.custom_cgm_ref_no = project.project_name
		return

	ref = build_cgm_ref_no(
		normalize_shipment_classification(
			project.get("custom_shipment_type"),
			project.get("custom_mode_of_transport"),
		)[0],
		project.get("custom_mode_of_transport"),
		project.get("custom_opened_date"),
	)
	project.project_name = ref
	if project.meta.has_field("custom_cgm_ref_no"):
		project.custom_cgm_ref_no = ref


# ─── Project Field Helpers ────────────────────────────────────────────────────


def apply_shipment_data(project, shipment_type=None, mode=None):
	"""Set shipment classification; derive mode from operational shipment type when known."""
	if shipment_type:
		project.custom_shipment_type = shipment_type
	if mode and project.meta.has_field("custom_mode_of_transport"):
		project.custom_mode_of_transport = mode

	normalized_type, derived_mode = normalize_shipment_classification(
		project.get("custom_shipment_type"),
		project.get("custom_mode_of_transport"),
	)
	if normalized_type:
		project.custom_shipment_type = normalized_type
	if derived_mode and project.meta.has_field("custom_mode_of_transport"):
		project.custom_mode_of_transport = derived_mode

	project_fields = frappe.get_meta("Project")
	if project_fields.has_field("custom_shipment_status"):
		project.custom_shipment_status = "Draft"


def normalize_shipment_classification(shipment_type=None, mode=None):
	"""
	Return (shipment_type, mode) using operational types (Sea FCL, Air Import, …).

	Legacy CRM values (Import/Export + Sea/Air/Road) are mapped for old records only.
	"""
	st = (shipment_type or "").strip()
	m = (mode or "").strip()

	row = get_shipment_type_record(st)
	if row:
		return row.shipment_type_name or st, mode_from_master(st) or m

	# Legacy Lead/Opportunity: Import + mode → operational default (blank mode → Sea FCL).
	if st == "Import":
		if m in ("", "Sea", None):
			return "Sea FCL", "Sea"
		if m == "Air":
			return "Air Import", "Air"
		if m == "Road":
			return "Cross-Border Road Import", "Road"
		return "Sea FCL", "Sea"
	if st == "Export":
		return "Export", m or "Sea"
	if st == "Transit":
		return "Transit", m or "Sea"
	if st == "Road Import":
		return "Cross-Border Road Import", "Road"

	return st or None, m or None


def normalize_shipment_fields_on_doc(doc) -> None:
	"""Rewrite legacy Import/Export values before Select validation on save."""
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

def get_container_type_order() -> list[str]:
	"""Pull container types from Container Type DocType ordered by idx."""
	return frappe.get_all(
		"Container Type",
		fields=["container_type"],
		order_by="idx asc",
		pluck="container_type",
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
	return frappe.get_all(
		"Container",
		filters={"parent": bill_of_lading, "parenttype": "Bill of Lading"},
		fields=get_container_fields(),
		order_by="idx asc",
	)

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


# ─── Preshipment container sync (Opportunity / Lead / Project) ─────────────────
def sync_preshipment_containers_from_bl(doc, method=None) -> None:
	"""Populate read-only container rows from the linked Bill of Lading before save."""
	config = get_bl_config()
	bl_field = config.get("opportunity_bl_field")
	container_field = config.get("opportunity_container_field")

	if not bl_field or not container_field:
		return
	if not doc.meta.has_field(container_field):
		return

	bl_name = doc.get(bl_field)
	rows = fetch_container_rows(bl_name) if bl_name else []

	doc.set(container_field, [])
	for row in rows:
		doc.append(
			container_field,
			{field: row.get(field) or "" for field in get_container_fields()},
		)

def apply_bill_of_lading_from_source(target_doc, source_doc) -> None:
	"""Copy Bill of Lading link and container rows from source onto target doc."""
	config = get_bl_config()
	bl_field = config.get("opportunity_bl_field")

	if not bl_field or not source_doc or not target_doc.meta.has_field(bl_field):
		return

	bl_name = source_doc.get(bl_field)
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
		if row.get("type_of_container"):
			parts.append(str(row.type_of_container))
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
		"containers": fetch_container_rows(bl_name),
		"quantity": get_bl_quantity_summary(bl_doc),
		"attachment": bl_doc.get(attachment_field) or "" if attachment_field else "",
	}

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
		{"label": "Shipment", "items": ["Bill of Lading", "Air Waybill"]},
		{"label": "Project", "items": ["Project"]},
	]
	non_standard = data.setdefault("non_standard_fieldnames", {})
	non_standard["Bill of Lading"] = "linked_opportunity"
	non_standard["Air Waybill"] = "linked_opportunity"
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
