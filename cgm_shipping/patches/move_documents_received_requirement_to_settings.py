"""Move the CI / PKL requirement for Documents Received from code into Settings.

Why: moving a shipment to Documents Received needed CI and PKL, listed in code
(INTAKE_DOCUMENT_CODES), so it could not be changed from the desk. Settings >
Shipment status documents already maps a status to Document Type stages.

What: when Settings has no Documents Received row, puts CI and PKL in their own
"Client documents" stage (only if still on Pre-IDF or blank - other Pre-IDF types
such as KRA PIN are untouched) and adds the row Documents Received -> Client
documents with Must Be Verified off, since the old rule accepted an attached,
unverified file. Behaviour stays the same; the rule is now editable.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe

STATUS = "Documents Received"
STAGE = "Client documents"
FIELD = "custom_workflow_stage_requirements"


def execute():
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		get_document_type_link_name,
	)

	if not frappe.db.table_exists("Workflow Stage Requirement Item"):
		return
	if frappe.db.exists(
		"Workflow Stage Requirement Item",
		{"parent": "CGM Shipping Settings", "parentfield": FIELD, "shipment_workflow_state": STATUS},
	):
		return

	for code in ("CI", "PKL"):
		name = get_document_type_link_name(code)
		if name and (frappe.db.get_value("Document Type", name, "required_stage") or "") in ("", "Pre-IDF"):
			frappe.db.set_value("Document Type", name, "required_stage", STAGE, update_modified=False)

	idx = frappe.db.count("Workflow Stage Requirement Item", {"parent": "CGM Shipping Settings", "parentfield": FIELD})
	frappe.get_doc(
		{
			"doctype": "Workflow Stage Requirement Item",
			"parent": "CGM Shipping Settings",
			"parenttype": "CGM Shipping Settings",
			"parentfield": FIELD,
			"idx": idx + 1,
			"shipment_workflow_state": STATUS,
			"required_stage": STAGE,
			"verified_required": 0,
		}
	).db_insert()
	frappe.clear_document_cache("CGM Shipping Settings", "CGM Shipping Settings")
