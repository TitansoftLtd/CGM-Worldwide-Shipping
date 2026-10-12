"""Required Document Types on CGM Task Template → Task Documents.

Template rows store comma-separated Document Type names (Data field).
Legacy Table MultiSelect child rows are flattened on migrate.
Legacy labels (e.g. Entry Slip vs Entry) are coerced via resolve_legacy_document_type_name.
"""
from __future__ import annotations

import frappe

# Legacy free-text labels → Document Type codes/names to try (migration + old stamps only).
_LEGACY_DOCUMENT_TYPE_LOOKUPS: dict[str, tuple[str, ...]] = {
	"Entry Slip": ("ENTRY", "Entry Slip", "Entry"),
	"entry slip": ("ENTRY", "Entry Slip", "Entry"),
	"ENTRY_SLIP": ("ENTRY", "Entry Slip", "Entry"),
	"Shipping Line": ("SHIPPING_LINE", "Shipping Line", "Shipping Line Invoice"),
	"KPA": ("KPA", "KPA Invoice"),
	"IDF CERT": ("IDF_CERT", "IDF Certificate", "IDF"),
	"IDF_CERT": ("IDF_CERT", "IDF Certificate", "IDF"),
}


def parse_required_document_types(value: str | None) -> list[str]:
	"""Split comma-separated Document Type names (exact master names only)."""
	if not value:
		return []
	return [part.strip() for part in str(value).split(",") if part.strip()]


def serialize_required_document_types(names: list[str]) -> str:
	"""Comma-separated stamp stored on Task.custom_required_document_types."""
	return ", ".join(name for name in names if name)


def resolve_legacy_document_type_name(token: str) -> str | None:
	"""Map a stored token to a Document Type name (exact match, then legacy/code lookup)."""
	token = (token or "").strip()
	if not token:
		return None
	if frappe.db.exists("Document Type", token):
		return token

	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		get_document_type_link_name,
	)

	candidates = [token, *_LEGACY_DOCUMENT_TYPE_LOOKUPS.get(token, ())]
	seen = set()
	for candidate in candidates:
		if not candidate or candidate in seen:
			continue
		seen.add(candidate)
		name = get_document_type_link_name(candidate)
		if name:
			return name
		if frappe.db.exists("Document Type", candidate):
			return candidate
	return None


def coerce_legacy_document_type_tokens(tokens: list[str]) -> list[str]:
	"""Normalize legacy / mixed labels to canonical Document Type names."""
	resolved: list[str] = []
	seen: set[str] = set()
	for token in tokens:
		name = resolve_legacy_document_type_name(token)
		if name and name not in seen:
			seen.add(name)
			resolved.append(name)
	return resolved


def document_type_names_from_template_row(row) -> list[str]:
	"""Document Type names selected on a CGM Task Template Item row.

	The field is a comma-separated Data field. It was a Table MultiSelect before
	flatten_template_required_document_multiselect; child rows are still accepted
	so a row read before that patch ran does not lose its selections.
	"""
	raw = (
		row.get("required_document_types")
		if isinstance(row, dict)
		else getattr(row, "required_document_types", None)
	)
	if not raw:
		return []

	# Current shape: "COC, LOA". Iterating this as child rows walks characters and
	# yields nothing, which silently dropped every requirement at task creation.
	if isinstance(raw, str):
		return coerce_legacy_document_type_tokens(parse_required_document_types(raw))

	names: list[str] = []
	for child in raw:
		if isinstance(child, dict):
			dt_name = (child.get("document_type") or "").strip()
		else:
			dt_name = (getattr(child, "document_type", "") or "").strip()
		if dt_name and frappe.db.exists("Document Type", dt_name):
			names.append(dt_name)
	return names


def resolve_required_document_type_name(token: str) -> str | None:
	"""Resolve a stored token when seeding Task Documents (supports legacy stamps)."""
	return resolve_legacy_document_type_name(token)


def normalize_required_document_type_stamp(value: str | None) -> str:
	"""Rewrite a Task stamp string to canonical Document Type names."""
	return serialize_required_document_types(
		coerce_legacy_document_type_tokens(parse_required_document_types(value))
	)
