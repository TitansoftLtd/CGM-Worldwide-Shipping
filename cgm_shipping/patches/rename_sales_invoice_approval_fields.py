"""Rename Sales Invoice approval Custom Fields (drop Finance prefix).

Why: Approval fields used custom_finance_* names; invoices are created by
finance users and only need clear Approved By / Rejected By / Rejection Reason.

What: Rename Custom Field fieldnames, update labels/depends_on/read_only, and
align field_order Property Setter references. Idempotent.

Does not change Quotation or any other DocType.
"""

from __future__ import annotations

import json

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SALES_INVOICE_APPROVED_BY_FIELD,
	SALES_INVOICE_REJECTED_BY_FIELD,
	SALES_INVOICE_REJECTION_REASON_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _upsert_cf

DT = "Sales Invoice"

_FIELD_RENAMES = (
	("custom_finance_approved_by", SALES_INVOICE_APPROVED_BY_FIELD, "Approved By"),
	("custom_finance_rejected_by", SALES_INVOICE_REJECTED_BY_FIELD, "Rejected By"),
	("custom_finance_rejection_reason", SALES_INVOICE_REJECTION_REASON_FIELD, "Rejection Reason"),
)


def execute() -> None:
	_rename_sales_invoice_approval_fields()
	_update_field_labels_and_flags()
	_update_property_setter_field_order()
	_sync_sales_invoice_workflow()
	frappe.clear_cache(doctype=DT)
	frappe.db.commit()


def _sync_sales_invoice_workflow() -> None:
	"""Keep Desk/workflow masters aligned with current SI approval constants."""
	from cgm_shipping.patches.ensure_sales_invoice_workflow import (
		_backfill_existing_sales_invoices,
		_ensure_workflow_action_masters,
		_sync_workflow,
	)

	_ensure_workflow_action_masters()
	_sync_workflow()
	_backfill_existing_sales_invoices()


def _rename_sales_invoice_approval_fields() -> None:
	for old_field, new_field, _label in _FIELD_RENAMES:
		_rename_custom_field(old_field, new_field)


def _rename_custom_field(old_field: str, new_field: str) -> None:
	old_name = f"{DT}-{old_field}"
	new_name = f"{DT}-{new_field}"

	if frappe.db.exists("Custom Field", new_name):
		if frappe.db.exists("Custom Field", old_name):
			frappe.delete_doc("Custom Field", old_name, force=1)
		return

	if not frappe.db.exists("Custom Field", old_name):
		return

	# rename_column auto-commits; tolerate a prior partial migrate.
	if frappe.db.has_column(DT, old_field) and not frappe.db.has_column(DT, new_field):
		frappe.db.rename_column(DT, old_field, new_field)

	frappe.db.set_value("Custom Field", old_name, "fieldname", new_field, update_modified=False)
	frappe.db.set_value(
		"Custom Field",
		{"dt": DT, "insert_after": old_field},
		"insert_after",
		new_field,
		update_modified=False,
	)
	frappe.rename_doc("Custom Field", old_name, new_name, force=True)


def _update_field_labels_and_flags() -> None:
	_upsert_cf(
		DT,
		{
			"fieldname": SALES_INVOICE_APPROVED_BY_FIELD,
			"label": "Approved By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "workflow_state",
			"read_only": 1,
			"allow_on_submit": 1,
		},
	)
	_upsert_cf(
		DT,
		{
			"fieldname": SALES_INVOICE_REJECTED_BY_FIELD,
			"label": "Rejected By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": SALES_INVOICE_APPROVED_BY_FIELD,
			"read_only": 1,
			"depends_on": "eval:doc.workflow_state=='Rejected'",
		},
	)
	_upsert_cf(
		DT,
		{
			"fieldname": SALES_INVOICE_REJECTION_REASON_FIELD,
			"label": "Rejection Reason",
			"fieldtype": "Small Text",
			"insert_after": SALES_INVOICE_REJECTED_BY_FIELD,
			"depends_on": "eval:doc.workflow_state=='Rejected'",
			"read_only": 1,
		},
	)


def _update_property_setter_field_order() -> None:
	ps_name = f"{DT}-main-field_order"
	if not frappe.db.exists("Property Setter", ps_name):
		return

	value = frappe.db.get_value("Property Setter", ps_name, "value") or "[]"
	try:
		order = json.loads(value)
	except Exception:
		return

	replacements = {old: new for old, new, _ in _FIELD_RENAMES}
	changed = False
	new_order = []
	for fieldname in order:
		replacement = replacements.get(fieldname, fieldname)
		if replacement != fieldname:
			changed = True
		if replacement not in new_order:
			new_order.append(replacement)

	if not changed:
		return

	frappe.db.set_value("Property Setter", ps_name, "value", json.dumps(new_order), update_modified=False)
