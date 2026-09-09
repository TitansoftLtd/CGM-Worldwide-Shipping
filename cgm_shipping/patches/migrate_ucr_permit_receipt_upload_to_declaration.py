"""Move UCR / Permit Upload Receipt responsibility to Declaration.

Stakeholder rule: the department that uploaded the invoice (Declaration)
also uploads the payment receipt when Finance pays. Client will pay /
Share Invoice / Make Payment remain with Finance.
"""

from __future__ import annotations


def execute():
	import frappe

	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		migrate_ucr_permit_receipt_upload_to_declaration,
	)

	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return
	if not frappe.db.exists("DocType", "CGM Document Responsibility Item"):
		return

	settings = frappe.get_doc("CGM Shipping Settings")
	if not migrate_ucr_permit_receipt_upload_to_declaration(settings):
		return
	settings.save(ignore_permissions=True)
	frappe.clear_cache()
