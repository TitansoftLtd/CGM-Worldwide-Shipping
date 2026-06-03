"""Map Permit Type → ERPNext Item for Purchase Invoice lines."""
from __future__ import annotations

import frappe

# Common Item name/code variants in CGM item master (longest / most specific first).
PERMIT_TYPE_ITEM_CANDIDATES: dict[str, tuple[str, ...]] = {
	"ACA": ("Aca Permit", "ACA Permit", "ACA", "Aca"),
	"DVS": ("Dvs Permit", "DVS Permit", "Dvs", "DVS"),
	"KEBS": ("Kebs Permit", "KEBS Permit", "Kebs", "KEBS"),
	"NBA": ("N.b.a", "NBA", "Nba", "N.b.a."),
	"VMD": ("Vmd Permit", "VMD Permit", "Vmd", "VMD"),
	"SCA": ("Sca Permit", "SCA Permit", "SCA", "Sca"),
	"KRPB": ("Krbp", "KRPB"),
	"Port Health": ("Port Health", "Port Healt"),
}


def _item_is_usable(item_code: str | None) -> bool:
	if not item_code or not frappe.db.exists("Item", item_code):
		return False
	disabled, is_purchase = frappe.db.get_value(
		"Item", item_code, ("disabled", "is_purchase_item")
	) or (1, 0)
	return not disabled and is_purchase


def _resolve_item_code(candidates: list[str]) -> str | None:
	seen: set[str] = set()
	for raw in candidates:
		code = (raw or "").strip()
		if not code or code in seen:
			continue
		seen.add(code)

		if _item_is_usable(code):
			return code

		rows = frappe.db.sql(
			"""
			SELECT name
			FROM `tabItem`
			WHERE disabled = 0
			  AND is_purchase_item = 1
			  AND (
				LOWER(name) = LOWER(%s)
				OR LOWER(item_name) = LOWER(%s)
			  )
			ORDER BY modified DESC
			LIMIT 1
			""",
			(code, code),
			pluck=True,
		)
		if rows:
			return rows[0]

		rows = frappe.db.sql(
			"""
			SELECT name
			FROM `tabItem`
			WHERE disabled = 0
			  AND is_purchase_item = 1
			  AND LOWER(item_name) LIKE LOWER(%s)
			ORDER BY LENGTH(item_name) ASC, modified DESC
			LIMIT 1
			""",
			(f"%{code}%",),
			pluck=True,
		)
		if rows:
			return rows[0]
	return None


def _permit_type_purchase_item_field_ready() -> bool:
	"""True when purchase_item exists in meta and database (after migrate)."""
	if not frappe.db.exists("DocType", "Permit Type"):
		return False
	meta = frappe.get_meta("Permit Type")
	if not meta.has_field("purchase_item"):
		return False
	return bool(frappe.db.has_column("Permit Type", "purchase_item"))


def candidates_for_permit_type(permit_type: str) -> list[str]:
	pt = (permit_type or "").strip()
	if not pt:
		return []

	out: list[str] = []
	for value in PERMIT_TYPE_ITEM_CANDIDATES.get(pt, ()):
		out.append(value)
	out.extend((f"{pt} Permit", pt, pt.upper(), pt.title()))
	return out


def resolve_purchase_item_for_permit_type(permit_type: str) -> str | None:
	"""Return Item code for a permit type, or None if no match."""
	if not permit_type:
		return None

	if _permit_type_purchase_item_field_ready() and frappe.db.exists("Permit Type", permit_type):
		linked = frappe.db.get_value("Permit Type", permit_type, "purchase_item")
		if _item_is_usable(linked):
			return linked

	return _resolve_item_code(candidates_for_permit_type(permit_type))


def get_purchase_item_for_permit_type(permit_type: str, company: str | None = None) -> str:
	"""Item for PI line — Permit Type master, then name match, then global default."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link import (
		get_default_purchase_item_code,
	)

	item = resolve_purchase_item_for_permit_type(permit_type)
	if item:
		return item
	return get_default_purchase_item_code(company)


def seed_permit_type_purchase_items() -> list[str]:
	"""Link Permit Type records to Items where a match exists."""
	if not frappe.db.exists("DocType", "Permit Type"):
		return []

	if not _permit_type_purchase_item_field_ready():
		return []

	updated: list[str] = []
	for name in frappe.get_all("Permit Type", pluck="name"):
		if frappe.db.get_value("Permit Type", name, "purchase_item"):
			continue
		item = resolve_purchase_item_for_permit_type(name)
		if not item:
			continue
		frappe.db.set_value("Permit Type", name, "purchase_item", item, update_modified=False)
		updated.append(f"{name} → {item}")
	return updated
