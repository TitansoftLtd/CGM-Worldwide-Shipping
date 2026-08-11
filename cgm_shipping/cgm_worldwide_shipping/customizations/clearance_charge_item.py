"""Clearance Charge Item master — dynamic labels for Task Invoices & Receipts."""

from __future__ import annotations

import frappe

LINE_INVOICE = "Invoice"
LINE_POP = "POP"
LINE_RECEIPT = "Receipt"

DEFAULT_PAYMENT_KINDS: tuple[dict, ...] = (
	{
		"payment_kind": "UCR",
		"description": "UCR / IDF finance payment grouping.",
	},
	{
		"payment_kind": "ENTRY_SLIP",
		"description": "Customs entry / e-slip finance payment grouping.",
	},
	{
		"payment_kind": "Shipping Line",
		"description": "Shipping line finance payment grouping.",
	},
	{
		"payment_kind": "Customs Entry",
		"description": "Customs entry finance payment grouping.",
	},
	{
		"payment_kind": "KPA",
		"description": "KPA port charge finance payment grouping.",
	},
)

DEFAULT_LINE_TYPES: tuple[dict, ...] = (
	{
		"line_type": "Invoice",
		"description": "Invoice line type.",
	},
	{
		"line_type": "Receipt",
		"description": "Receipt line type.",
	},
	{
		"line_type": "POP",
		"description": "Proof of payment / POP line type.",
	},
)


def ensure_payment_kinds() -> int:
	"""Create missing Payment Kind master rows used by Clearance Charge Item."""
	if not frappe.db.exists("DocType", "Payment Kind"):
		return 0

	created = 0
	for spec in DEFAULT_PAYMENT_KINDS:
		name = (spec.get("payment_kind") or "").strip()
		if not name:
			continue
		if frappe.db.exists("Payment Kind", name):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Payment Kind",
				"payment_kind": name,
				"is_active": 1,
				"description": spec.get("description") or "",
			}
		)
		doc.insert(ignore_permissions=True)
		created += 1
	return created


def ensure_line_types() -> int:
	"""Create missing Line Type master rows used by Clearance Charge Item."""
	if not frappe.db.exists("DocType", "Line Type"):
		return 0

	created = 0
	for spec in DEFAULT_LINE_TYPES:
		name = (spec.get("line_type") or "").strip()
		if not name:
			continue
		if frappe.db.exists("Line Type", name):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Line Type",
				"line_type": name,
				"is_active": 1,
				"description": spec.get("description") or "",
			}
		)
		doc.insert(ignore_permissions=True)
		created += 1
	return created


# Defaults seeded when missing. Ops can add more rows in Desk without code changes.
DEFAULT_CLEARANCE_CHARGE_ITEMS: tuple[dict, ...] = (
	{
		"charge_name": "UCR Invoice",
		"line_type": LINE_INVOICE,
		"payment_kind": "UCR",
		"description": "IDF / UCR supplier invoice on Create UCR / Finance pays UCR.",
	},
	{
		"charge_name": "UCR Receipt",
		"line_type": LINE_RECEIPT,
		"payment_kind": "UCR",
		"description": "Payment receipt after UCR is paid.",
	},
	{
		"charge_name": "Entry Slip Invoice",
		"line_type": LINE_INVOICE,
		"payment_kind": "ENTRY_SLIP",
		"description": "Customs entry / e-slip invoice.",
	},
	{
		"charge_name": "Entry Slip Receipt",
		"line_type": LINE_RECEIPT,
		"payment_kind": "ENTRY_SLIP",
		"description": "Receipt after entry taxes are paid.",
	},
	{
		"charge_name": "Shipping Line Invoice",
		"line_type": LINE_INVOICE,
		"payment_kind": "Shipping Line",
		"description": "Shipping line charges invoice.",
	},
	{
		"charge_name": "Shipping Line POP",
		"line_type": LINE_POP,
		"payment_kind": "Shipping Line",
		"description": "Proof of payment for shipping line charges.",
	},
	{
		"charge_name": "Shipping Line Receipt",
		"line_type": LINE_RECEIPT,
		"payment_kind": "Shipping Line",
		"description": "Official shipping line receipt.",
	},
	{
		"charge_name": "KPA Invoice",
		"line_type": LINE_INVOICE,
		"payment_kind": "KPA",
		"description": "KPA port charges invoice.",
	},
	{
		"charge_name": "KPA Receipt",
		"line_type": LINE_RECEIPT,
		"payment_kind": "KPA",
		"description": "KPA payment receipt.",
	},
)


def ensure_clearance_charge_items(*, sync_descriptions: bool = False) -> int:
	"""Create missing Clearance Charge Item defaults. Returns count created."""
	if not frappe.db.exists("DocType", "Clearance Charge Item"):
		return 0

	# Keep the payment-kind and line-type reference trees hydrated before building charge rows.
	ensure_payment_kinds()
	ensure_line_types()

	created = 0
	for spec in DEFAULT_CLEARANCE_CHARGE_ITEMS:
		name = (spec.get("charge_name") or "").strip()
		if not name:
			continue
		if frappe.db.exists("Clearance Charge Item", name):
			if sync_descriptions and spec.get("description"):
				current = frappe.db.get_value("Clearance Charge Item", name, "description") or ""
				if not current.strip():
					frappe.db.set_value(
						"Clearance Charge Item",
						name,
						"description",
						spec["description"],
						update_modified=False,
					)
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Clearance Charge Item",
				"charge_name": name,
				"line_type": spec["line_type"],
				"payment_kind": spec["payment_kind"],
				"is_active": 1,
				"description": spec.get("description") or "",
				"purchase_item": spec.get("purchase_item"),
			}
		)
		doc.insert(ignore_permissions=True)
		created += 1
	return created


def get_clearance_charge_item(
	payment_kind: str | None,
	line_type: str,
	*,
	fallback_label: str | None = None,
) -> str | None:
	"""Resolve Clearance Charge Item name for a payment kind + line type.

	Prefers an active row matching payment_kind + line_type. Falls back to an
	exact name match on ``fallback_label`` (legacy hardcoded labels).
	"""
	if not frappe.db.exists("DocType", "Clearance Charge Item"):
		return None

	kind = (payment_kind or "").strip()
	ltype = (line_type or "").strip()
	if kind and ltype:
		name = frappe.db.get_value(
			"Clearance Charge Item",
			{"payment_kind": kind, "line_type": ltype, "is_active": 1},
			"name",
			order_by="modified asc",
		)
		if name:
			return name

	label = (fallback_label or "").strip()
	if label and frappe.db.exists("Clearance Charge Item", label):
		return label
	return None


def get_charge_item_label(charge_item: str | None, fallback: str = "") -> str:
	if not charge_item:
		return fallback or ""
	if frappe.db.exists("Clearance Charge Item", charge_item):
		return (
			frappe.db.get_value("Clearance Charge Item", charge_item, "charge_name")
			or charge_item
		)
	return charge_item


def get_charge_item_purchase_item(charge_item: str | None) -> str | None:
	if not charge_item or not frappe.db.exists("Clearance Charge Item", charge_item):
		return None
	return frappe.db.get_value("Clearance Charge Item", charge_item, "purchase_item") or None


@frappe.request_cache
def task_finance_line_has_charge_item() -> bool:
	"""True when Task Finance Line.charge_item is installed (after bench migrate)."""
	meta = frappe.get_meta("Task Finance Line")
	if not meta.has_field("charge_item"):
		return False
	return bool(frappe.db.has_column("Task Finance Line", "charge_item"))


def build_finance_line_payload(
	line_type: str,
	payment_kind: str,
	*,
	fallback_label: str | None = None,
	company: str | None = None,
) -> dict:
	"""Build a Task Finance Line row dict with charge_item link and defaults."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_purchase_item_for_payment_item,
		task_finance_line_has_item_code,
	)

	charge_item = get_clearance_charge_item(
		payment_kind, line_type, fallback_label=fallback_label
	)
	label = get_charge_item_label(charge_item, fallback_label or "") or (fallback_label or "")

	payload: dict = {
		"line_label": label,
		"line_type": line_type,
		"payment_item": payment_kind,
	}
	if charge_item and task_finance_line_has_charge_item():
		payload["charge_item"] = charge_item

	if line_type == "Invoice" and task_finance_line_has_item_code():
		item_code = get_charge_item_purchase_item(charge_item)
		if not item_code:
			item_code = get_purchase_item_for_payment_item(payment_kind, company)
		if item_code:
			payload["item_code"] = item_code

	return payload


def backfill_task_finance_line_charge_items() -> int:
	"""Link existing Task Finance Line rows to Clearance Charge Item by payment + line type."""
	if not task_finance_line_has_charge_item():
		return 0

	updated = 0
	for row in frappe.db.get_all(
		"Task Finance Line",
		fields=["name", "line_type", "payment_item", "line_label", "charge_item"],
	):
		if row.charge_item:
			continue
		charge_item = get_clearance_charge_item(
			row.payment_item or "UCR",
			row.line_type or "Invoice",
			fallback_label=(row.line_label or "").strip() or None,
		)
		if not charge_item:
			continue
		frappe.db.set_value(
			"Task Finance Line",
			row.name,
			"charge_item",
			charge_item,
			update_modified=False,
		)
		updated += 1
	return updated


def clear_clearance_charge_item_caches() -> None:
	"""Drop stale Meta / FormMeta caches after schema or field layout changes."""
	doctype = "Clearance Charge Item"
	frappe.clear_cache(doctype=doctype)
	try:
		from frappe.model.meta import clear_meta_cache

		clear_meta_cache(doctype)
	except Exception:
		pass
	try:
		frappe.client_cache.delete_value(f"doctype_form_meta::{doctype}")
	except Exception:
		pass


def sync_task_finance_lines_from_charge_items() -> int:
	"""Refresh charge_item links, labels, and purchase items on existing finance rows."""
	if not task_finance_line_has_charge_item():
		return 0

	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		task_finance_line_has_item_code,
	)

	updated = 0
	for row in frappe.db.get_all(
		"Task Finance Line",
		fields=[
			"name",
			"line_type",
			"payment_item",
			"line_label",
			"charge_item",
			"item_code",
		],
	):
		charge_item = row.charge_item or get_clearance_charge_item(
			row.payment_item or "UCR",
			row.line_type or LINE_INVOICE,
			fallback_label=(row.line_label or "").strip() or None,
		)
		if not charge_item:
			continue

		updates: dict = {}
		if charge_item != (row.charge_item or ""):
			updates["charge_item"] = charge_item

		label = get_charge_item_label(charge_item, row.line_label or "")
		if label and label != (row.line_label or ""):
			updates["line_label"] = label

		if (
			(row.line_type or "") == LINE_INVOICE
			and task_finance_line_has_item_code()
		):
			purchase_item = get_charge_item_purchase_item(charge_item)
			if purchase_item and purchase_item != (row.item_code or ""):
				updates["item_code"] = purchase_item

		if not updates:
			continue
		frappe.db.set_value(
			"Task Finance Line",
			row.name,
			updates,
			update_modified=False,
		)
		updated += 1
	return updated


def repair_clearance_charge_item_setup() -> dict:
	"""Idempotent repair: caches, master rows, and Task Finance Line backfill."""
	if frappe.db.exists("DocType", "Payment Kind"):
		frappe.reload_doctype("Payment Kind", force=True)
	if frappe.db.exists("DocType", "Line Type"):
		frappe.reload_doctype("Line Type", force=True)
	if frappe.db.exists("DocType", "Clearance Charge Item"):
		frappe.reload_doctype("Clearance Charge Item", force=True)
	clear_clearance_charge_item_caches()
	created_payment_kinds = ensure_payment_kinds()
	created_line_types = ensure_line_types()
	created = ensure_clearance_charge_items()
	backfilled = backfill_task_finance_line_charge_items()
	synced = sync_task_finance_lines_from_charge_items()
	clear_clearance_charge_item_caches()
	return {
		"created_payment_kinds": created_payment_kinds,
		"created_line_types": created_line_types,
		"created_charge_items": created,
		"backfilled_charge_links": backfilled,
		"synced_finance_lines": synced,
	}
