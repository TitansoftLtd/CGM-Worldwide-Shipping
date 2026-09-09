"""Delete unused Opportunity field B/L Number (if known).

The Bill of Lading document already stores the BL number; Opportunity does not
need a draft copy. Idempotent: no-op when the Custom Field is already gone.
"""

from __future__ import annotations

import json

import frappe

DT = "Opportunity"
FIELD = "custom_draft_bl_number"
CF_NAME = f"{DT}-{FIELD}"
FIELD_ORDER = "Opportunity-main-field_order"


def execute() -> None:
	_remove_from_field_order()
	if frappe.db.exists("Custom Field", CF_NAME):
		frappe.delete_doc("Custom Field", CF_NAME, force=1)
	frappe.clear_cache(doctype=DT)


def _remove_from_field_order() -> None:
	if not frappe.db.exists("Property Setter", FIELD_ORDER):
		return
	raw = frappe.db.get_value("Property Setter", FIELD_ORDER, "value") or ""
	try:
		order = json.loads(raw)
	except (TypeError, ValueError):
		return
	if not isinstance(order, list) or FIELD not in order:
		return
	order = [field for field in order if field != FIELD]
	frappe.db.set_value(
		"Property Setter", FIELD_ORDER, "value", json.dumps(order), update_modified=False
	)
