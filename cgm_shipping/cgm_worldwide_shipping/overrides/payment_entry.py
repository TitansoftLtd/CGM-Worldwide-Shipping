# Copyright (c) 2026, Titansoft Limited and contributors
"""Clearance payments use standard Payment Entry.project link."""

from __future__ import annotations

import frappe


def validate_shipment_link(doc, method=None):
	if doc.project and not frappe.db.exists("Project", doc.project):
		frappe.throw(f"Project {doc.project} does not exist")
