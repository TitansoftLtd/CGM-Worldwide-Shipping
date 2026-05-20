# Copyright (c) 2026, Titansoft Limited and contributors
"""Link Payment Entry to Shipment Dossier per implementation guide."""

from __future__ import annotations

import frappe


def validate_shipment_link(doc, method=None):
	"""Ensure custom_shipment_dossier is set when payment references shipment charges."""
	if getattr(doc, "custom_shipment_dossier", None):
		if not frappe.db.exists("Shipment Dossier", doc.custom_shipment_dossier):
			frappe.throw(f"Shipment Dossier {doc.custom_shipment_dossier} does not exist")
