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
	ordered: list[str] = []
	for row in frappe.get_all(
		"Cargo Size",
		fields=["name", "cargo_size"],
		order_by="idx asc",
	):
		label = (row.get("cargo_size") or row.get("name") or "").strip()
		if label and label not in ordered:
			ordered.append(label)
	return ordered


def normalize_cargo_size(size: str | None) -> str:
	"""Canonical Cargo Size link name for batch matching."""
	raw = (size or "").strip()
	if not raw:
		return ""
	return resolve_cargo_size_link(raw) or raw


def counts_from_derived_quantity_text(derived_quantity: str | None) -> dict[str, int]:
	"""Parse ``2 x 20FT, 1 x 40FT`` into ``{size: qty}``."""
	text = (derived_quantity or "").strip()
	if not text or " x " not in text.lower():
		return {}

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
	return counts


def normalize_derived_quantity(derived_quantity: str | None) -> str:
	"""Parse and re-canonicalize a derived quantity string for batch matching."""
	return format_derived_quantity(counts_from_derived_quantity_text(derived_quantity))


def request_row_cargo_size(row) -> str:
	"""Cargo size from a Requested Containers row (incl. legacy container_size)."""
	if isinstance(row, dict):
		raw = row.get("cargo_size") or row.get("container_size") or ""
	else:
		raw = getattr(row, "cargo_size", None) or getattr(row, "container_size", None) or ""
	return normalize_cargo_size(str(raw).strip())


def request_row_quantity(row) -> int:
	"""Integer quantity from a Requested Containers row."""
	if isinstance(row, dict):
		raw = row.get("quantity")
	else:
		raw = getattr(row, "quantity", None)
	text = str(raw or "").strip()
	if " x " in text.lower():
		# User pasted a derived string into the quantity cell.
		counts = counts_from_derived_quantity_text(text)
		if len(counts) == 1:
			return next(iter(counts.values()))
	return cint(text)


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
		size = request_row_cargo_size(row)
		qty = request_row_quantity(row)
		if not size:
			# Quantity cell may hold a full derived string (e.g. ``3 x 20FT``).
			if isinstance(row, dict):
				raw_qty = str(row.get("quantity") or "").strip()
			else:
				raw_qty = str(getattr(row, "quantity", None) or "").strip()
			parsed = counts_from_derived_quantity_text(raw_qty)
			for parsed_size, parsed_qty in parsed.items():
				counts[parsed_size] = counts.get(parsed_size, 0) + parsed_qty
			continue
		if qty <= 0:
			continue
		counts[size] = counts.get(size, 0) + qty
	return counts


def requested_cargo_rows_from_counts(counts: Mapping[str, int]) -> list[dict]:
	"""Build Requested Containers row dicts from size→qty counts."""
	text = format_derived_quantity(counts)
	parsed = counts_from_derived_quantity_text(text) if text else dict(counts or {})
	return [
		{"cargo_size": size, "quantity": str(qty)}
		for size, qty in parsed.items()
		if size and cint(qty) > 0
	]


def hydrate_requested_cargo_rows(doc, table_field: str = "requested_cargo_quantity") -> bool:
	"""Ensure Requested Containers rows have cargo_size (+ numeric quantity).

	Recovers size from legacy ``container_size``, from a derived string pasted into
	the quantity cell, or from the parent derived-quantity field when child sizes
	were not persisted.
	"""
	if not doc.meta.has_field(table_field):
		return False

	rows = list(doc.get(table_field) or [])
	changed = False
	counts = counts_from_request_rows(rows)

	if not counts:
		parent_qty = ""
		if doc.meta.has_field("quantity"):
			parent_qty = str(doc.get("quantity") or "").strip()
		counts = counts_from_derived_quantity_text(parent_qty)

	if not counts:
		return False

	# Rebuild rows when any size is missing or quantity is a derived string.
	needs_rebuild = False
	if len(rows) != len(counts):
		needs_rebuild = True
	else:
		for row in rows:
			size = request_row_cargo_size(row)
			raw_qty = (
				str(row.get("quantity") or "").strip()
				if isinstance(row, dict)
				else str(getattr(row, "quantity", None) or "").strip()
			)
			if not size or " x " in raw_qty.lower():
				needs_rebuild = True
				break

	if not needs_rebuild:
		# Still normalize link values / quantity digits onto existing rows.
		for row in rows:
			size = request_row_cargo_size(row)
			qty = request_row_quantity(row)
			if not size or qty <= 0:
				continue
			if isinstance(row, dict):
				if row.get("cargo_size") != size:
					row["cargo_size"] = size
					changed = True
				if str(row.get("quantity") or "") != str(qty):
					row["quantity"] = str(qty)
					changed = True
			else:
				if row.get("cargo_size") != size:
					row.cargo_size = size
					changed = True
				if str(row.get("quantity") or "") != str(qty):
					row.quantity = str(qty)
					changed = True
		return changed

	new_rows = requested_cargo_rows_from_counts(counts)
	doc.set(table_field, [])
	for row in new_rows:
		doc.append(table_field, row)
	return True


def counts_from_container_rows(rows: Iterable | None) -> dict[str, int]:
	"""Aggregate Bill of Lading container rows (one physical container per row)."""
	counts: dict[str, int] = {}
	for row in rows or []:
		size = normalize_cargo_size(container_row_cargo_size(row))
		if not size:
			continue
		counts[size] = counts.get(size, 0) + 1
	return counts


def size_sequence_from_counts(counts: Mapping[str, int]) -> list[str]:
	"""Expand size→qty counts into an ordered list of sizes (display order)."""
	text = format_derived_quantity(counts)
	parsed = counts_from_derived_quantity_text(text) if text else dict(counts or {})
	if not parsed:
		return []

	display_order = _cargo_size_display_order()
	ordered = [size for size in display_order if size in parsed]
	for size in sorted(parsed):
		if size not in ordered:
			ordered.append(size)

	sequence: list[str] = []
	for size in ordered:
		sequence.extend([size] * cint(parsed[size]))
	return sequence


def _set_container_row_cargo_size(row, size: str) -> bool:
	"""Set cargo_size on a child row dict/doc; return True when the value changed."""
	link = resolve_cargo_size_link(size) or normalize_cargo_size(size) or size
	if not link:
		return False
	current = container_row_cargo_size(row)
	if current == link:
		return False
	if isinstance(row, dict):
		row["cargo_size"] = link
	else:
		row.cargo_size = link
	return True


def fill_missing_container_row_cargo_sizes(rows, derived_quantity: str | None) -> bool:
	"""Stamp cargo_size onto container rows that lack it, using parent derived quantity.

	- Single size in derived qty (e.g. ``3 x 20FT``): fill every empty row with that size.
	- Multiple sizes: only when *all* rows are missing size and the expanded sequence
	  length matches the row count (same order as booking stubs).
	Never overwrites an existing cargo_size.
	"""
	rows = list(rows or [])
	if not rows:
		return False

	counts = counts_from_derived_quantity_text(derived_quantity)
	if not counts:
		return False

	missing = [row for row in rows if not normalize_cargo_size(container_row_cargo_size(row))]
	if not missing:
		return False

	if len(counts) == 1:
		size = next(iter(counts.keys()))
		changed = False
		for row in missing:
			if _set_container_row_cargo_size(row, size):
				changed = True
		return changed

	# Mixed sizes: only auto-assign when every row is blank and counts match.
	if len(missing) != len(rows):
		return False
	sequence = size_sequence_from_counts(counts)
	if len(sequence) != len(rows):
		return False

	changed = False
	for row, size in zip(rows, sequence, strict=True):
		if _set_container_row_cargo_size(row, size):
			changed = True
	return changed


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
