"""Ensure container deposit custom fields (Journal Entry + Task mirror).

Bill of Lading / Container deposit fields live in DocType JSON.
Idempotent — safe to re-run on every migrate.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	_ensure_cf,
)


def execute() -> None:
	_ensure_journal_entry_deposit_fields()
	_ensure_sales_invoice_deposit_source_fields()
	_ensure_task_deposit_fields()
	_ensure_project_deposit_refund_fields()
	_ensure_settings_deposit_fields()
	frappe.db.commit()


def _ensure_sales_invoice_deposit_source_fields() -> None:
	insert_after = "project"
	if not frappe.db.exists("Custom Field", "Sales Invoice-project"):
		insert_after = "customer"
	for values in (
		{
			"fieldname": "custom_cgm_source_task",
			"label": "CGM Source Task",
			"fieldtype": "Link",
			"options": "Task",
			"insert_after": insert_after,
			"read_only": 1,
			"hidden": 1,
		},
		{
			"fieldname": "custom_cgm_source_bill_of_lading",
			"label": "CGM Source Bill of Lading",
			"fieldtype": "Link",
			"options": "Bill of Lading",
			"insert_after": "custom_cgm_source_task",
			"read_only": 1,
			"hidden": 1,
		},
	):
		_ensure_cf("Sales Invoice", values)
	frappe.clear_cache(doctype="Sales Invoice")


def _ensure_journal_entry_deposit_fields() -> None:
	for values in (
		{
			"fieldname": "custom_cgm_source_container_tracker",
			"label": "CGM Source Container Tracker",
			"fieldtype": "Link",
			"options": "Container Tracker",
			"insert_after": "custom_cgm_source_task",
			"read_only": 1,
		},
		{
			"fieldname": "custom_cgm_source_bill_of_lading",
			"label": "CGM Source Bill of Lading",
			"fieldtype": "Link",
			"options": "Bill of Lading",
			"insert_after": "custom_cgm_source_container_tracker",
			"read_only": 1,
		},
		{
			"fieldname": "custom_cgm_deposit_entry_kind",
			"label": "CGM Deposit Entry Kind",
			"fieldtype": "Select",
			"options": "\nOutbound\nRefund",
			"insert_after": "custom_cgm_source_bill_of_lading",
			"read_only": 1,
		},
	):
		_ensure_cf("Journal Entry", values)
	frappe.clear_cache(doctype="Journal Entry")


def _ensure_task_deposit_fields() -> None:
	insert_after = "custom_payment_kind"
	if not frappe.db.exists("Custom Field", "Task-custom_payment_kind"):
		insert_after = "custom_section_container_updates"

	_ensure_cf(
		"Task",
		{
			"fieldname": "custom_bl_deposit_arrangement",
			"label": "BL Deposit Arrangement",
			"fieldtype": "Data",
			"insert_after": insert_after,
			"read_only": 1,
			"description": "Mirrored from Bill of Lading (Container Deposit or Revolving Fund).",
		},
	)
	_ensure_cf(
		"Task",
		{
			"fieldname": "custom_deposit_payer",
			"label": "Container Deposit Paid By",
			"fieldtype": "Select",
			"options": "\nAgent\nCustomer\nCompany",
			"insert_after": "custom_bl_deposit_arrangement",
			"description": "Finance confirms who pays the container deposit (saved on Bill of Lading).",
		},
	)
	# Legacy mirror — hide if still present
	if frappe.db.exists("Custom Field", "Task-custom_bl_has_deposit"):
		frappe.db.set_value(
			"Custom Field",
			"Task-custom_bl_has_deposit",
			{"hidden": 1, "read_only": 1},
			update_modified=False,
		)
	frappe.clear_cache(doctype="Task")


def _ensure_project_deposit_refund_fields() -> None:
	insert_after = "custom_bill_of_lading"
	if not frappe.db.exists("Custom Field", "Project-custom_bill_of_lading"):
		insert_after = "customer"
	for values in (
		{
			"fieldname": "custom_section_container_deposit_refund",
			"label": "Container Deposit Refund",
			"fieldtype": "Section Break",
			"insert_after": insert_after,
			"collapsible": 1,
			"depends_on": "eval:doc.custom_bill_of_lading",
		},
		{
			"fieldname": "custom_container_deposit_refund_status",
			"label": "Deposit Refund Status",
			"fieldtype": "Data",
			"insert_after": "custom_section_container_deposit_refund",
			"read_only": 1,
			"description": "Mirrored from the linked Bill of Lading after all containers are returned.",
		},
		{
			"fieldname": "custom_container_deposit_refund_confirmed",
			"label": "Deposit Refund Confirmed",
			"fieldtype": "Check",
			"insert_after": "custom_container_deposit_refund_status",
			"read_only": 1,
			"description": "Set when Finance confirms the shipping line returned the container deposit.",
		},
		{
			"fieldname": "custom_column_break_deposit_refund",
			"fieldtype": "Column Break",
			"insert_after": "custom_container_deposit_refund_confirmed",
		},
		{
			"fieldname": "custom_container_deposit_refund_confirmed_by",
			"label": "Refund Confirmed By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "custom_column_break_deposit_refund",
			"read_only": 1,
		},
		{
			"fieldname": "custom_container_deposit_refund_confirmed_on",
			"label": "Refund Confirmed On",
			"fieldtype": "Datetime",
			"insert_after": "custom_container_deposit_refund_confirmed_by",
			"read_only": 1,
		},
	):
		_ensure_cf("Project", values)
	frappe.clear_cache(doctype="Project")


def _ensure_settings_deposit_fields() -> None:
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return
	meta = frappe.get_meta("CGM Shipping Settings")
	if meta.has_field("container_deposit_sales_item"):
		frappe.clear_cache(doctype="CGM Shipping Settings")
		return
	_ensure_cf(
		"CGM Shipping Settings",
		{
			"fieldname": "container_deposit_sales_item",
			"label": "Container Deposit Sales Item",
			"fieldtype": "Link",
			"options": "Item",
			"insert_after": "container_deposit_account",
			"description": "Item used on Sales Invoices for the container deposit line (Customer / Company paths).",
		},
	)
	frappe.clear_cache(doctype="CGM Shipping Settings")
