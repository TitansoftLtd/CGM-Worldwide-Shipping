"""CGM tracking-sheet reference generation and shipment-type/mode classification.

Depends only on frappe, so it has no import cycle with utils - which re-exports
these names for callers that still import them from
cgm_shipping...customizations.utils.
"""

from __future__ import annotations

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
