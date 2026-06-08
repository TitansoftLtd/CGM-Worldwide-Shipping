"""Link a submitted Bill of Lading to its source Opportunity and sync the BL attachment."""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.bl_containers import (
	summarize_bl_container_quantities,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	OPPORTUNITY_DOCUMENTS_FIELD,
	document_types_match,
	ensure_document_types,
	get_document_type_link_name,
)

BL_ATTACHMENT_FIELD = "bill_of_lading"
OPPORTUNITY_BL_FIELD = "custom_bill_of_lading"
OPPORTUNITY_QUANTITY_FIELD = "custom_quantity"
BL_SOURCE_OPPORTUNITY_FIELD = "custom_linked_opportunity"


def is_valid_opportunity_link(opportunity: str | None) -> bool:
	"""True when opportunity is a saved CRM Opportunity name (not a local draft id)."""
	if not opportunity:
		return False
	name = str(opportunity).strip()
	if not name or name.startswith("new-"):
		return False
	return bool(frappe.db.exists("Opportunity", name))


def sanitize_bill_of_lading_linked_opportunity(doc) -> None:
	"""Drop unsaved/local Opportunity ids so Link validation does not block BL save."""
	opp = doc.get(BL_SOURCE_OPPORTUNITY_FIELD)
	if opp and not is_valid_opportunity_link(opp):
		doc.set(BL_SOURCE_OPPORTUNITY_FIELD, None)


def _resolve_opportunity_for_bl(bl_doc, opportunity: str | None = None) -> str | None:
	"""Return a saved Opportunity name linked to this Bill of Lading."""
	linked = bl_doc.get(BL_SOURCE_OPPORTUNITY_FIELD)
	if is_valid_opportunity_link(linked):
		return linked
	if is_valid_opportunity_link(opportunity):
		frappe.db.set_value(
			"Bill of Lading",
			bl_doc.name,
			BL_SOURCE_OPPORTUNITY_FIELD,
			opportunity,
			update_modified=False,
		)
		bl_doc.set(BL_SOURCE_OPPORTUNITY_FIELD, opportunity)
		return opportunity
	return None


def sync_opportunity_from_submitted_bl(
	bl_doc, opportunity: str | None = None, enforce_permissions: bool = False
) -> str | None:
	"""Link submitted BL data back onto the source Opportunity.

	``enforce_permissions`` must be set for user-initiated calls (e.g. the
	whitelisted endpoint) so a user cannot mutate an Opportunity they lack write
	access to. The ``on_submit`` hook runs as a system side-effect and leaves it off.
	"""
	opportunity = _resolve_opportunity_for_bl(bl_doc, opportunity)
	if not opportunity:
		return None

	if enforce_permissions:
		frappe.has_permission("Opportunity", ptype="write", doc=opportunity, throw=True)

	opp = frappe.get_doc("Opportunity", opportunity)
	changed = False

	if opp.get(OPPORTUNITY_BL_FIELD) != bl_doc.name:
		opp.set(OPPORTUNITY_BL_FIELD, bl_doc.name)
		changed = True

	attachment_url = bl_doc.get(BL_ATTACHMENT_FIELD)
	if attachment_url and opp.meta.has_field(OPPORTUNITY_DOCUMENTS_FIELD):
		if prepend_opportunity_bl_document(opp, attachment_url, bl_name=bl_doc.name):
			changed = True

	quantity_summary = summarize_bl_container_quantities(bl_doc.name)
	if quantity_summary and opp.meta.has_field(OPPORTUNITY_QUANTITY_FIELD):
		if opp.get(OPPORTUNITY_QUANTITY_FIELD) != quantity_summary:
			opp.set(OPPORTUNITY_QUANTITY_FIELD, quantity_summary)
			changed = True

	if changed:
		opp.save(ignore_permissions=True)

	return opportunity


@frappe.whitelist()
def get_bl_submit_payload(bl_name: str, opportunity: str | None = None) -> dict:
	"""Return BL link + attachment metadata for applying on the Opportunity form after submit."""
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		frappe.throw("Bill of Lading not found", frappe.DoesNotExistError)

	frappe.has_permission("Bill of Lading", ptype="read", doc=bl_name, throw=True)
	doc = frappe.get_doc("Bill of Lading", bl_name)
	if doc.docstatus != 1:
		frappe.throw("Bill of Lading must be submitted first.")

	ensure_document_types()
	linked_opportunity = sync_opportunity_from_submitted_bl(
		doc, opportunity, enforce_permissions=True
	)
	return {
		"bl_name": doc.name,
		"attachment": doc.get(BL_ATTACHMENT_FIELD),
		"document_type": get_document_type_link_name("BL"),
		"quantity": summarize_bl_container_quantities(doc.name),
		"opportunity": linked_opportunity,
	}


def bill_of_lading_on_submit(doc, method=None):
	"""After BL submit: link to Opportunity and prepend BL file in Clients Documents."""
	sync_opportunity_from_submitted_bl(doc)


def prepend_opportunity_bl_document(opp_doc, attachment_url, bl_name=None):
	"""Insert or refresh the BL row as the first Clients Documents entry on Opportunity."""
	if not attachment_url or not opp_doc.meta.has_field(OPPORTUNITY_DOCUMENTS_FIELD):
		return False

	ensure_document_types()
	document_type = get_document_type_link_name("BL")
	if not document_type:
		return False

	field = OPPORTUNITY_DOCUMENTS_FIELD
	existing = list(opp_doc.get(field) or [])
	other_rows = [
		row
		for row in existing
		if not document_types_match(row.document_type, document_type)
	]

	remarks = frappe._("From submitted Bill of Lading {0}").format(bl_name or "")
	new_row = {
		"document_type": document_type,
		"attachment": attachment_url,
		"status": "Uploaded",
		"uploaded_by": frappe.session.user,
		"uploaded_on": now_datetime(),
		"remarks": remarks,
	}

	opp_doc.set(field, [])
	opp_doc.append(field, new_row)
	for row in other_rows:
		opp_doc.append(
			field,
			{
				"document_type": row.document_type,
				"attachment": row.attachment,
				"status": row.status,
				"uploaded_by": row.uploaded_by,
				"uploaded_on": row.uploaded_on,
				"verified_by": row.verified_by,
				"verified_on": row.verified_on,
				"remarks": row.remarks,
			},
		)
	return True
