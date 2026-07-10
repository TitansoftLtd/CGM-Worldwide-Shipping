"""Ensure CGM Shipping Settings has last_batch_no initialized from existing data."""

from __future__ import annotations

import frappe
from frappe.utils import cint


def execute():
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return

	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("last_batch_no"):
		return

	current = frappe.db.get_single_value("CGM Shipping Settings", "last_batch_no")
	if current not in (None, "", 0):
		return

	max_batch = 0
	if frappe.db.has_column("Opportunity", "custom_batch_no"):
		rows = frappe.db.sql(
			"""
			SELECT custom_batch_no FROM `tabOpportunity`
			WHERE IFNULL(custom_batch_no, '') REGEXP '^[0-9]+$'
			"""
		)
		for (value,) in rows:
			max_batch = max(max_batch, cint(value))

	if max_batch <= 0 and frappe.db.has_column("Bill of Lading", "batch_no"):
		rows = frappe.db.sql(
			"""
			SELECT batch_no FROM `tabBill of Lading`
			WHERE IFNULL(batch_no, '') REGEXP '^[0-9]+$'
			"""
		)
		for (value,) in rows:
			max_batch = max(max_batch, cint(value))

	frappe.db.set_single_value(
		"CGM Shipping Settings",
		"last_batch_no",
		max_batch,
	)
	frappe.db.commit()
