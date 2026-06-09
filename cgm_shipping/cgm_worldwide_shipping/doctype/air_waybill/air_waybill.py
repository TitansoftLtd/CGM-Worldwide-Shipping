# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Air Waybill controller and its Opportunity-sync logic.

Mirrors the Bill of Lading flow for air freight: an Air Waybill branches a CRM
Opportunity (carrying the customer, shipment type, description and the AWB
document) and an Opportunity surfaces its Air Waybill under Connections. Air
freight has no container manifest, so the container/quantity sync the Bill of
Lading carries does not apply here.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	document_types_match,
	ensure_document_types,
	get_document_type_link_name,
	get_opportunity_documents_field,
)

# Air Waybill -> Opportunity (back-link on this doctype) and Opportunity -> AWB.
OPPORTUNITY_SOURCE_FIELD = "linked_opportunity"
OPPORTUNITY_AWB_FIELD = "custom_airway_bill"
DOCUMENT_TYPE_CODE = "AWB"


class AirWaybill(Document):
	def autoname(self):
		# Name by the Air Waybill number (naming_rule: "By script").
		if not self.air_waybill:
			frappe.throw(frappe._("Air Waybill number is required"))
		self.name = self.air_waybill

	def validate(self):
		sanitize_air_waybill_linked_opportunity(self)

	def on_submit(self):
		"""Keep the linked Opportunity aligned once the Air Waybill is submitted."""
		sync_opportunity_from_submitted_awb(self)


# ─── Opportunity link validation ──────────────────────────────────────────────
def is_valid_opportunity_link(opportunity: str | None) -> bool:
	"""True when opportunity is a saved CRM Opportunity name."""
	if not opportunity:
		return False
	name = str(opportunity).strip()
	if not name or name.startswith("new-"):
		return False
	return bool(frappe.db.exists("Opportunity", name))


def sanitize_air_waybill_linked_opportunity(doc) -> None:
	"""Drop unsaved Opportunity ids so Link validation does not block AWB save."""
	opp = doc.get(OPPORTUNITY_SOURCE_FIELD)
	if opp and not is_valid_opportunity_link(opp):
		doc.set(OPPORTUNITY_SOURCE_FIELD, None)


# ─── Opportunity sync ─────────────────────────────────────────────────────────
def sync_opportunity_from_submitted_awb(awb_doc, opportunity: str | None = None) -> str | None:
	"""Link submitted AWB data back onto the source Opportunity."""
	opportunity = opportunity or awb_doc.get(OPPORTUNITY_SOURCE_FIELD)
	if not is_valid_opportunity_link(opportunity):
		return None

	opp = frappe.get_doc("Opportunity", opportunity)
	changed = False

	if opp.meta.has_field(OPPORTUNITY_AWB_FIELD) and opp.get(OPPORTUNITY_AWB_FIELD) != awb_doc.name:
		opp.set(OPPORTUNITY_AWB_FIELD, awb_doc.name)
		changed = True

	attachment_url = awb_doc.get("attach_airwaybill")
	clients_field = get_opportunity_documents_field()
	if attachment_url and clients_field and opp.meta.has_field(clients_field):
		if prepend_opportunity_awb_document(opp, attachment_url, awb_name=awb_doc.name):
			changed = True

	if changed:
		opp.save(ignore_permissions=True)

	return opportunity


def prepend_opportunity_awb_document(opp_doc, attachment_url, awb_name=None) -> bool:
	"""Insert the AWB row as the first Clients Documents entry on the Opportunity."""
	field = get_opportunity_documents_field()
	if not attachment_url or not field or not opp_doc.meta.has_field(field):
		return False

	ensure_document_types()
	document_type = get_document_type_link_name(DOCUMENT_TYPE_CODE)
	if not document_type:
		return False

	existing = list(opp_doc.get(field) or [])
	other_rows = [
		row for row in existing if not document_types_match(row.document_type, document_type)
	]

	opp_doc.set(field, [])
	opp_doc.append(
		field,
		{
			"document_type": document_type,
			"attachment": attachment_url,
			"status": "Uploaded",
			"uploaded_by": frappe.session.user,
			"uploaded_on": now_datetime(),
			"remarks": frappe._("From submitted Air Waybill {0}").format(awb_name or ""),
		},
	)
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


# ─── Whitelisted API ──────────────────────────────────────────────────────────
@frappe.whitelist()
def create_opportunity_from_air_waybill(air_waybill: str) -> str:
	"""Create a CRM Opportunity from a submitted Air Waybill.

	The Customer carried on the AWB becomes the Opportunity party; the AWB link,
	shipment type, description and attachment flow onto the new Opportunity, and
	the AWB is back-linked so both records stay in step. Re-running this returns
	the already-linked Opportunity instead of creating a duplicate.
	"""
	frappe.has_permission("Opportunity", ptype="create", throw=True)

	if not air_waybill or not frappe.db.exists("Air Waybill", air_waybill):
		frappe.throw("Air Waybill not found", frappe.DoesNotExistError)

	frappe.has_permission("Air Waybill", ptype="read", doc=air_waybill, throw=True)
	awb = frappe.get_doc("Air Waybill", air_waybill)

	if awb.docstatus != 1:
		frappe.throw("Air Waybill must be submitted before creating an Opportunity.")

	# An Air Waybill maps to a single Opportunity: return the existing one
	# instead of creating a duplicate.
	existing = awb.get(OPPORTUNITY_SOURCE_FIELD)
	if is_valid_opportunity_link(existing):
		return existing

	existing = frappe.db.get_value("Opportunity", {OPPORTUNITY_AWB_FIELD: awb.name}, "name")
	if existing:
		if awb.meta.has_field(OPPORTUNITY_SOURCE_FIELD):
			frappe.db.set_value(
				"Air Waybill", awb.name, OPPORTUNITY_SOURCE_FIELD, existing, update_modified=False
			)
		return existing

	customer = awb.get("customer")
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw("Set a Customer on the Air Waybill before creating an Opportunity.")

	opp = frappe.new_doc("Opportunity")
	opp.opportunity_from = "Customer"
	opp.party_name = customer

	if opp.meta.has_field(OPPORTUNITY_AWB_FIELD):
		opp.set(OPPORTUNITY_AWB_FIELD, awb.name)
	# An Air Waybill is an air-freight document, so default the mode to Air.
	if opp.meta.has_field("custom_mode_of_transport") and not opp.get("custom_mode_of_transport"):
		opp.set("custom_mode_of_transport", "Air")
	if opp.meta.has_field("custom_consignee"):
		opp.set(
			"custom_consignee",
			frappe.db.get_value("Customer", customer, "customer_name") or customer,
		)

	# Carry the shipment classification details from the AWB onto the Opportunity.
	if opp.meta.has_field("custom_shipment_type") and awb.get("shipment_type"):
		opp.set("custom_shipment_type", awb.get("shipment_type"))
	if opp.meta.has_field("custom_description_of_goods") and awb.get("description"):
		opp.set("custom_description_of_goods", awb.get("description"))

	# Add the AWB attachment as the first row of the Opportunity documents table.
	attachment_url = awb.get("attach_airwaybill")
	clients_field = get_opportunity_documents_field()
	if attachment_url and clients_field and opp.meta.has_field(clients_field):
		prepend_opportunity_awb_document(opp, attachment_url, awb_name=awb.name)

	opp.insert()

	# Back-link the AWB so the on_submit sync keeps both records aligned.
	if awb.meta.has_field(OPPORTUNITY_SOURCE_FIELD):
		frappe.db.set_value(
			"Air Waybill", awb.name, OPPORTUNITY_SOURCE_FIELD, opp.name, update_modified=False
		)

	return opp.name
