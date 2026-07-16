"""Ensure Container Tracker deposit fields exist in DB (has_deposit, deposit_payment_status)."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("DocType", "Container Tracker"):
		return

	missing = [
		field
		for field in ("has_deposit", "deposit_payment_status")
		if not frappe.db.has_column("Container Tracker", field)
	]
	if not missing:
		return

	try:
		frappe.reload_doc(
			"cgm_worldwide_shipping",
			"doctype",
			"container_tracker",
		)
	except Exception:
		frappe.log_error(
			title="Container Tracker deposit fields patch",
			message=frappe.get_traceback(),
		)
		return

	frappe.clear_cache(doctype="Container Tracker")
