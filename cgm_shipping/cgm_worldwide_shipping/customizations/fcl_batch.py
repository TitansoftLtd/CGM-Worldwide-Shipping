# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""FCL batch number allocation — Customer + Derived Quantity.

Applies only to FCL shipments. LCL must not use this sequence.

Batch is assigned when creating a Booking Confirmation or Bill of Lading (when
container configuration is known). The sequence is per customer and per derived
quantity profile (e.g. ``2 x 40FT`` vs ``2 x 20FT`` are separate counters).
Booking → BL reuses the same batch when linked.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import frappe
from frappe.utils import cint

from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	container_row_cargo_size,
	resolve_cargo_size_link,
)

FCL_CARGO_TYPE = "FCL"
LCL_CARGO_TYPE = "LCL"


def is_fcl_cargo_type(cargo_type: str | None) -> bool:
	return (cargo_type or "").strip().upper() == FCL_CARGO_TYPE


def is_lcl_cargo_type(cargo_type: str | None) -> bool:
	return (cargo_type or "").strip().upper() == LCL_CARGO_TYPE


def _cargo_size_display_order() -> list[str]:
	if not frappe.db.exists("DocType", "Cargo Size"):
		return []
	return frappe.get_all(
		"Cargo Size",
		fields=["cargo_size"],
		order_by="idx asc",
		pluck="cargo_size",
	) or []


def normalize_cargo_size(size: str | None) -> str:
	"""Canonical Cargo Size link name for batch matching."""
	raw = (size or "").strip()
	if not raw:
		return ""
	return resolve_cargo_size_link(raw) or raw


def normalize_derived_quantity(derived_quantity: str | None) -> str:
	"""Parse and re-canonicalize a derived quantity string for batch matching."""
	text = (derived_quantity or "").strip()
	if not text or " x " not in text.lower():
		return text

	counts: dict[str, int] = {}
	for part in (segment.strip() for segment in text.split(",")):
		if not part or " x " not in part.lower():
			continue
		qty_text, size_text = part.rsplit(" x ", 1)
		qty = cint((qty_text or "").strip())
		size = normalize_cargo_size((size_text or "").strip())
		if not size or qty <= 0:
			continue
		counts[size] = counts.get(size, 0) + qty
	return format_derived_quantity(counts)


def format_derived_quantity(counts: Mapping[str, int]) -> str:
	"""Canonical derived quantity, e.g. ``2 x 20FT, 1 x 40FT``."""
	cleaned: dict[str, int] = {}
	for size, qty in (counts or {}).items():
		normalized_size = normalize_cargo_size(str(size).strip())
		parsed_qty = cint(qty)
		if not normalized_size or parsed_qty <= 0:
			continue
		cleaned[normalized_size] = cleaned.get(normalized_size, 0) + parsed_qty
	if not cleaned:
		return ""

	display_order = _cargo_size_display_order()
	ordered = [size for size in display_order if size in cleaned]
	for size in sorted(cleaned):
		if size not in ordered:
			ordered.append(size)
	return ", ".join(f"{cleaned[size]} x {size}" for size in ordered)


def counts_from_request_rows(rows: Iterable | None) -> dict[str, int]:
	"""Aggregate Booking / Opportunity requested-container rows (size + quantity)."""
	counts: dict[str, int] = {}
	for row in rows or []:
		if isinstance(row, dict):
			size = normalize_cargo_size((row.get("cargo_size") or "").strip())
			qty = cint(row.get("quantity") or 0)
		else:
			size = normalize_cargo_size((getattr(row, "cargo_size", None) or "").strip())
			qty = cint(getattr(row, "quantity", None) or 0)
		if not size or qty <= 0:
			continue
		counts[size] = counts.get(size, 0) + qty
	return counts


def counts_from_container_rows(rows: Iterable | None) -> dict[str, int]:
	"""Aggregate Bill of Lading container rows (one physical container per row)."""
	counts: dict[str, int] = {}
	for row in rows or []:
		size = normalize_cargo_size(container_row_cargo_size(row))
		if not size:
			continue
		counts[size] = counts.get(size, 0) + 1
	return counts


def derived_quantity_from_booking(doc) -> str:
	"""FCL derived quantity from Booking Confirmation request rows."""
	if is_lcl_cargo_type(doc.get("requested_cargo_type")):
		return ""
	return format_derived_quantity(
		counts_from_request_rows(doc.get("requested_cargo_quantity"))
	)


def derived_quantity_from_bl(doc) -> str:
	"""FCL derived quantity from Bill of Lading container rows."""
	if is_lcl_cargo_type(doc.get("cargo_type")):
		return ""
	return format_derived_quantity(
		counts_from_container_rows(doc.get("container_information"))
	)


def lock_customer_for_fcl_batch(customer: str) -> None:
	if not customer:
		return
	frappe.db.sql(
		"SELECT name FROM `tabCustomer` WHERE name = %s FOR UPDATE",
		(customer,),
	)


def _max_batch_from_doctype(
	doctype: str,
	*,
	customer: str,
	derived_quantity: str,
	cargo_type_field: str,
	exclude_name: str | None = None,
) -> int:
	"""Highest batch_no for Customer + Derived Quantity on one DocType (draft + submitted)."""
	if not frappe.db.exists("DocType", doctype):
		return 0
	meta = frappe.get_meta(doctype)
	if not meta.has_field("batch_no") or not meta.has_field("quantity"):
		return 0
	if not meta.has_field(cargo_type_field):
		return 0

	target = normalize_derived_quantity(derived_quantity)
	if not target:
		return 0

	conditions = [
		"customer = %(customer)s",
		"docstatus < 2",
		"IFNULL(batch_no, '') REGEXP '^[0-9]+$'",
		"IFNULL(quantity, '') LIKE '%% x %%'",
	]
	values: dict = {"customer": customer}
	if exclude_name:
		conditions.append("name != %(exclude_name)s")
		values["exclude_name"] = exclude_name

	rows = frappe.db.sql(
		f"""
		SELECT batch_no, quantity, `{cargo_type_field}` AS cargo_type
		FROM `tab{doctype}`
		WHERE {" AND ".join(conditions)}
		""",
		values,
		as_dict=True,
	)

	highest = 0
	for row in rows or []:
		if is_lcl_cargo_type(row.get("cargo_type")):
			continue
		if normalize_derived_quantity(row.get("quantity")) != target:
			continue
		highest = max(highest, cint(row.get("batch_no")))
	return highest


def next_fcl_batch_number(
	*,
	customer: str,
	derived_quantity: str,
	exclude_name: str | None = None,
) -> int:
	"""Next batch for Customer + Derived Quantity (FCL only)."""
	customer = (customer or "").strip()
	derived_quantity = normalize_derived_quantity(derived_quantity)
	if not customer or not derived_quantity:
		frappe.throw(
			frappe._(
				"Customer and container quantity are required to allocate an FCL batch number."
			),
			title=frappe._("FCL Batch"),
		)

	lock_customer_for_fcl_batch(customer)

	highest = max(
		_max_batch_from_doctype(
			"Bill of Lading",
			customer=customer,
			derived_quantity=derived_quantity,
			cargo_type_field="cargo_type",
			exclude_name=exclude_name,
		),
		_max_batch_from_doctype(
			"Booking Confirmation",
			customer=customer,
			derived_quantity=derived_quantity,
			cargo_type_field="requested_cargo_type",
			exclude_name=exclude_name,
		),
	)
	return highest + 1


def allocate_fcl_batch_for_doc(doc, *, cargo_type_field: str, derived_quantity: str) -> int | None:
	"""Set ``quantity`` + ``batch_no`` on an FCL Booking/BL. Returns batch or None for LCL/incomplete."""
	cargo_type = doc.get(cargo_type_field)
	if is_lcl_cargo_type(cargo_type):
		return None
	if cargo_type and not is_fcl_cargo_type(cargo_type):
		return None

	derived = normalize_derived_quantity(derived_quantity or "")
	if not derived:
		return None

	if doc.meta.has_field("quantity"):
		doc.quantity = derived

	if doc.meta.has_field(cargo_type_field) and not is_lcl_cargo_type(doc.get(cargo_type_field)):
		doc.set(cargo_type_field, FCL_CARGO_TYPE)

	# Prefer batch already allocated on a linked Booking Confirmation (BL path).
	booking_name = (doc.get("booking_confirmation") or "").strip()
	if booking_name and frappe.db.exists("Booking Confirmation", booking_name):
		booking_batch = frappe.db.get_value("Booking Confirmation", booking_name, "batch_no")
		if booking_batch and str(booking_batch).strip().isdigit():
			batch = int(str(booking_batch).strip())
			if doc.meta.has_field("batch_no"):
				doc.batch_no = str(batch)
			return batch

	existing = str(doc.get("batch_no") or "").strip()
	# Ignore pre-seeded batch on new docs (e.g. stale Opportunity global counter).
	if existing.isdigit() and not doc.is_new():
		return int(existing)
	if doc.meta.has_field("batch_no"):
		doc.batch_no = None

	batch = next_fcl_batch_number(
		customer=doc.get("customer"),
		derived_quantity=derived,
		exclude_name=doc.name if not doc.is_new() else None,
	)
	if doc.meta.has_field("batch_no"):
		doc.batch_no = str(batch)
	return batch
