"""Ensure container charge fields, settings, project totals, and JE accrual schema."""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import (
	_ensure_cf,
)


def execute() -> None:
	_ensure_container_tracker_charge_fields()
	_ensure_cgm_settings_charge_fields()
	_ensure_project_charge_total_fields()
	_ensure_journal_entry_accrual_fields()
	_ensure_container_child_summary_fields()
	frappe.db.commit()


def _ensure_container_tracker_charge_fields() -> None:
	for values in (
		{
			"fieldname": "section_container_charges",
			"label": "Accrued Charges",
			"fieldtype": "Section Break",
			"insert_after": "kpa_days",
			"collapsible": 0,
		},
		{
			"fieldname": "demurrage_daily_rate",
			"label": "Demurrage/Detention Daily Rate",
			"fieldtype": "Currency",
			"insert_after": "section_container_charges",
			"description": "From shipping line tiers or flat rate. Edit to override calculated amount.",
		},
		{
			"fieldname": "demurrage_rate_currency",
			"label": "Demurrage Currency",
			"fieldtype": "Link",
			"options": "Currency",
			"insert_after": "demurrage_daily_rate",
		},
		{
			"fieldname": "demurrage_amount",
			"label": "Demurrage/Detention Amount Accrued",
			"fieldtype": "Currency",
			"insert_after": "demurrage_rate_currency",
			"read_only": 1,
			"bold": 1,
		},
		{
			"fieldname": "demurrage_amount_adjustment",
			"label": "Demurrage Adjustment",
			"fieldtype": "Currency",
			"insert_after": "demurrage_amount",
			"description": "Added to the calculated demurrage total when the rate table is slightly off.",
		},
		{
			"fieldname": "column_break_container_charges",
			"fieldtype": "Column Break",
			"insert_after": "demurrage_amount_adjustment",
		},
		{
			"fieldname": "kpa_port_daily_rate",
			"label": "KPA Port Daily Rate",
			"fieldtype": "Currency",
			"insert_after": "column_break_container_charges",
			"description": "From CGM Settings. Edit to override on this container.",
		},
		{
			"fieldname": "kpa_rate_currency",
			"label": "KPA Port Currency",
			"fieldtype": "Link",
			"options": "Currency",
			"insert_after": "kpa_port_daily_rate",
		},
		{
			"fieldname": "kpa_amount",
			"label": "KPA Port Amount Accrued",
			"fieldtype": "Currency",
			"insert_after": "kpa_rate_currency",
			"read_only": 1,
			"bold": 1,
		},
		{
			"fieldname": "kpa_amount_adjustment",
			"label": "KPA Port Adjustment",
			"fieldtype": "Currency",
			"insert_after": "kpa_amount",
		},
		{
			"fieldname": "section_container_charges_posted",
			"label": "Posted to Journal",
			"fieldtype": "Section Break",
			"insert_after": "kpa_amount_adjustment",
			"collapsible": 1,
		},
		{
			"fieldname": "demurrage_amount_posted_to_je",
			"label": "Demurrage Posted to JE",
			"fieldtype": "Currency",
			"insert_after": "section_container_charges_posted",
			"read_only": 1,
		},
		{
			"fieldname": "kpa_amount_posted_to_je",
			"label": "KPA Port Posted to JE",
			"fieldtype": "Currency",
			"insert_after": "demurrage_amount_posted_to_je",
			"read_only": 1,
		},
	):
		_ensure_cf("Container Tracker", values)
	frappe.clear_cache(doctype="Container Tracker")


def _ensure_cgm_settings_charge_fields() -> None:
	"""Charge fields live on CGM Shipping Settings doctype JSON — drop legacy Custom Fields."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _remove_cf

	for fieldname in (
		"default_dem_currency",
		"section_kpa_port_charges",
		"kpa_port_daily_rate",
		"kpa_port_rate_currency",
		"section_container_accrual_accounts",
		"demurrage_accrual_expense_account",
		"demurrage_accrual_payable_account",
		"column_break_accrual_accounts",
		"kpa_port_accrual_expense_account",
		"kpa_port_accrual_payable_account",
	):
		_remove_cf("CGM Shipping Settings", fieldname)
	frappe.clear_cache(doctype="CGM Shipping Settings")


def _ensure_project_charge_total_fields() -> None:
	for values in (
		{
			"fieldname": "custom_section_container_charge_summary",
			"label": "Container Charge Accruals",
			"fieldtype": "Section Break",
			"insert_after": "custom_finance_cost_total",
			"collapsible": 1,
		},
		{
			"fieldname": "custom_demurrage_accrued_total",
			"label": "Demurrage/Detention Accrued Total",
			"fieldtype": "Currency",
			"insert_after": "custom_section_container_charge_summary",
			"read_only": 1,
			"bold": 1,
			"hidden": 1,
		},
		{
			"fieldname": "custom_demurrage_accrued_total_display",
			"label": "Demurrage/Detention Accrued Total",
			"fieldtype": "Data",
			"insert_after": "custom_section_container_charge_summary",
			"read_only": 1,
			"bold": 1,
		},
		{
			"fieldname": "custom_kpa_port_accrued_total",
			"label": "KPA Port Accrued Total",
			"fieldtype": "Currency",
			"insert_after": "custom_demurrage_accrued_total_display",
			"read_only": 1,
			"bold": 1,
			"hidden": 1,
		},
		{
			"fieldname": "custom_kpa_port_accrued_total_display",
			"label": "KPA Port Accrued Total",
			"fieldtype": "Data",
			"insert_after": "custom_demurrage_accrued_total_display",
			"read_only": 1,
			"bold": 1,
		},
		{
			"fieldname": "custom_demurrage_accrued_posted_total",
			"label": "Demurrage Posted to JE Total",
			"fieldtype": "Currency",
			"insert_after": "custom_kpa_port_accrued_total_display",
			"read_only": 1,
			"hidden": 1,
		},
		{
			"fieldname": "custom_demurrage_accrued_posted_total_display",
			"label": "Demurrage Posted to JE Total",
			"fieldtype": "Data",
			"insert_after": "custom_kpa_port_accrued_total_display",
			"read_only": 1,
		},
		{
			"fieldname": "custom_kpa_port_accrued_posted_total",
			"label": "KPA Port Posted to JE Total",
			"fieldtype": "Currency",
			"insert_after": "custom_demurrage_accrued_posted_total_display",
			"read_only": 1,
			"hidden": 1,
		},
		{
			"fieldname": "custom_kpa_port_accrued_posted_total_display",
			"label": "KPA Port Posted to JE Total",
			"fieldtype": "Data",
			"insert_after": "custom_demurrage_accrued_posted_total_display",
			"read_only": 1,
		},
	):
		_ensure_cf("Project", values)
	frappe.clear_cache(doctype="Project")


def _ensure_journal_entry_accrual_fields() -> None:
	for values in (
		{
			"fieldname": "custom_cgm_source_project",
			"label": "CGM Source Project",
			"fieldtype": "Link",
			"options": "Project",
			"insert_after": "custom_cgm_source_task",
			"read_only": 1,
		},
		{
			"fieldname": "custom_cgm_accrual_kind",
			"label": "CGM Accrual Kind",
			"fieldtype": "Data",
			"insert_after": "custom_cgm_source_project",
			"read_only": 1,
		},
		{
			"fieldname": "custom_cgm_container_charge_lines",
			"label": "Container Charge Lines",
			"fieldtype": "Table",
			"options": "CGM Container Charge Accrual Line",
			"insert_after": "custom_cgm_accrual_kind",
			"read_only": 1,
		},
	):
		_ensure_cf("Journal Entry", values)
	frappe.clear_cache(doctype="Journal Entry")


def _ensure_container_child_summary_fields() -> None:
	for values in (
		{
			"fieldname": "kpa_days",
			"label": "KPA Chargeable Days",
			"fieldtype": "Int",
			"insert_after": "demurrage_days",
			"fetch_from": "container_tracker.kpa_days",
			"read_only": 1,
			"in_list_view": 1,
		},
		{
			"fieldname": "demurrage_amount",
			"label": "Demurrage Amount",
			"fieldtype": "Currency",
			"insert_after": "kpa_days",
			"fetch_from": "container_tracker.demurrage_amount",
			"read_only": 1,
			"in_list_view": 1,
		},
		{
			"fieldname": "kpa_amount",
			"label": "KPA Port Amount",
			"fieldtype": "Currency",
			"insert_after": "demurrage_amount",
			"fetch_from": "container_tracker.kpa_amount",
			"read_only": 1,
			"in_list_view": 1,
		},
	):
		_ensure_cf("Container", values)
	frappe.clear_cache(doctype="Container")

