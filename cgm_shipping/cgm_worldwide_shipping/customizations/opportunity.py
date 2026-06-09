# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Opportunity server-side customizations."""

import frappe
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	get_opportunity_documents_field,
)

# Approved state of the "CGM Opportunity Pre-Shipment" workflow.
APPROVED_WORKFLOW_STATE = "Approved"

# Doctypes that carry a soft back-link to the Opportunity via "linked_opportunity".
BACK_LINKED_DOCTYPES = ("Air Waybill", "Bill of Lading")


def clear_back_links_on_trash(doc, method=None) -> None:
	for doctype in BACK_LINKED_DOCTYPES:
		for name in frappe.get_all(
			doctype, filters={"linked_opportunity": doc.name}, pluck="name"
		):
			frappe.db.set_value(
				doctype, name, "linked_opportunity", None, update_modified=False
			)


def stamp_verified_documents_on_approval(doc, method=None) -> None:
	"""Stamp Verified By / Verified On on the document rows once the Opportunity
	is Approved in its workflow. Only fills rows not yet verified, so re-saving an
	already-approved Opportunity does not churn the values."""
	if doc.get("workflow_state") != APPROVED_WORKFLOW_STATE:
		return

	field = get_opportunity_documents_field()
	if not field or not doc.meta.has_field(field):
		return

	for row in doc.get(field) or []:
		if not row.verified_by:
			row.verified_by = frappe.session.user
		if not row.verified_on:
			row.verified_on = now_datetime()
