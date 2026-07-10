# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Booking Confirmation — primary transport document for export-style shipments.

Mirrors Bill of Lading / Air Waybill Opportunity sync: create from Opportunity,
submit back-populates Opportunity, return to Opportunity for verification.
No container numbers at this stage — those are captured later after empties
are collected.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
	ensure_document_types,
	get_document_type_link_name,
	get_opportunity_documents_field,
	prepend_clients_document_row,
)

OPPORTUNITY_SOURCE_FIELD = "linked_opportunity"
OPPORTUNITY_BOOKING_FIELD = "custom_booking_confirmation"
DOCUMENT_TYPE_CODE = "BOOKING"


class BookingConfirmation(Document):
	def validate(self):
		sanitize_booking_linked_opportunity(self)

	def on_submit(self):
		sync_opportunity_from_submitted_booking(self)


def is_valid_opportunity_link(opportunity: str | None) -> bool:
	if not opportunity:
		return False
	name = str(opportunity).strip()
	if not name or name.startswith("new-"):
		return False
	return bool(frappe.db.exists("Opportunity", name))


def sanitize_booking_linked_opportunity(doc) -> None:
	opp = doc.get(OPPORTUNITY_SOURCE_FIELD)
	if opp and not is_valid_opportunity_link(opp):
		doc.set(OPPORTUNITY_SOURCE_FIELD, None)


def sync_opportunity_from_submitted_booking(booking_doc, opportunity: str | None = None) -> str | None:
	"""Link submitted Booking Confirmation data onto the source Opportunity."""
	opportunity = opportunity or booking_doc.get(OPPORTUNITY_SOURCE_FIELD)
	if not is_valid_opportunity_link(opportunity):
		return None

	opp = frappe.get_doc("Opportunity", opportunity)
	changed = False

	if opp.meta.has_field(OPPORTUNITY_BOOKING_FIELD) and opp.get(OPPORTUNITY_BOOKING_FIELD) != booking_doc.name:
		opp.set(OPPORTUNITY_BOOKING_FIELD, booking_doc.name)
		changed = True

	field_map = (
		("shipping_line", "custom_shipping_line"),
		("vessel", "custom_vessel"),
		("etd", "custom_etd"),
		("eta", "custom_eta"),
		("booking_number", "custom_booking_ref"),
		("booking_number", "custom_shipping_order_ref"),
		("commodity", "custom_description_of_goods"),
		("client_ref", "custom_client_refrence_no"),
	)
	for src, dest in field_map:
		if not opp.meta.has_field(dest):
			continue
		value = booking_doc.get(src)
		if value not in (None, "") and not opp.get(dest):
			opp.set(dest, value)
			changed = True

	if (
		opp.meta.has_field("custom_shipment_type")
		and booking_doc.get("shipment_type")
		and not opp.get("custom_shipment_type")
	):
		opp.set("custom_shipment_type", booking_doc.shipment_type)
		changed = True

	if booking_doc.get("requested_container_quantity") and opp.meta.has_field("custom_quantity"):
		qty = booking_doc.requested_container_quantity
		ctype = booking_doc.get("requested_container_type") or ""
		summary = f"{qty} x {ctype}".strip() if ctype else str(qty)
		if not opp.get("custom_quantity"):
			opp.set("custom_quantity", summary)
			changed = True

	attachment_url = booking_doc.get("attach_booking")
	clients_field = get_opportunity_documents_field()
	if attachment_url and clients_field and opp.meta.has_field(clients_field):
		if prepend_opportunity_booking_document(opp, attachment_url, booking_name=booking_doc.name):
			changed = True

	if changed:
		opp.save(ignore_permissions=True)

	return opportunity


def prepend_opportunity_booking_document(opp_doc, attachment_url, booking_name=None) -> bool:
	field = get_opportunity_documents_field()
	if not attachment_url or not field or not opp_doc.meta.has_field(field):
		return False

	ensure_document_types()
	document_type = get_document_type_link_name(DOCUMENT_TYPE_CODE)
	if not document_type:
		return False

	return prepend_clients_document_row(
		opp_doc,
		field,
		document_type,
		attachment_url,
		status="Uploaded",
		remarks=frappe._("From submitted Booking Confirmation {0}").format(booking_name or ""),
	)


@frappe.whitelist()
def get_booking_submit_payload(booking_name: str, opportunity: str | None = None) -> dict:
	if not booking_name or not frappe.db.exists("Booking Confirmation", booking_name):
		frappe.throw("Booking Confirmation not found", frappe.DoesNotExistError)

	frappe.has_permission("Booking Confirmation", ptype="read", doc=booking_name, throw=True)
	doc = frappe.get_doc("Booking Confirmation", booking_name)
	if doc.docstatus != 1:
		frappe.throw("Booking Confirmation must be submitted first.")

	linked_opportunity = sync_opportunity_from_submitted_booking(doc, opportunity)
	return {
		"booking_name": doc.name,
		"attachment": doc.get("attach_booking") or "",
		"document_type": get_document_type_link_name(DOCUMENT_TYPE_CODE),
		"opportunity": linked_opportunity,
		"shipment_type": doc.get("shipment_type"),
		"booking_number": doc.get("booking_number"),
	}


@frappe.whitelist()
def create_opportunity_from_booking_confirmation(booking_confirmation: str) -> str:
	"""Create a CRM Opportunity from a submitted Booking Confirmation (reverse flow)."""
	frappe.has_permission("Opportunity", ptype="create", throw=True)

	if not booking_confirmation or not frappe.db.exists("Booking Confirmation", booking_confirmation):
		frappe.throw("Booking Confirmation not found", frappe.DoesNotExistError)

	frappe.has_permission("Booking Confirmation", ptype="read", doc=booking_confirmation, throw=True)
	booking = frappe.get_doc("Booking Confirmation", booking_confirmation)

	if booking.docstatus != 1:
		frappe.throw("Booking Confirmation must be submitted before creating an Opportunity.")

	existing = booking.get(OPPORTUNITY_SOURCE_FIELD)
	if is_valid_opportunity_link(existing):
		return existing

	existing = frappe.db.get_value(
		"Opportunity", {OPPORTUNITY_BOOKING_FIELD: booking.name}, "name"
	)
	if existing:
		if booking.meta.has_field(OPPORTUNITY_SOURCE_FIELD):
			frappe.db.set_value(
				"Booking Confirmation",
				booking.name,
				OPPORTUNITY_SOURCE_FIELD,
				existing,
				update_modified=False,
			)
		return existing

	customer = booking.get("customer")
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw("Set a Customer on the Booking Confirmation before creating an Opportunity.")

	opp = frappe.new_doc("Opportunity")
	opp.opportunity_from = "Customer"
	opp.party_name = customer

	if opp.meta.has_field(OPPORTUNITY_BOOKING_FIELD):
		opp.set(OPPORTUNITY_BOOKING_FIELD, booking.name)
	if opp.meta.has_field("custom_shipment_type") and booking.get("shipment_type"):
		opp.set("custom_shipment_type", booking.shipment_type)
	if opp.meta.has_field("custom_consignee"):
		opp.set(
			"custom_consignee",
			frappe.db.get_value("Customer", customer, "customer_name") or customer,
		)

	attachment_url = booking.get("attach_booking")
	clients_field = get_opportunity_documents_field()
	if attachment_url and clients_field and opp.meta.has_field(clients_field):
		prepend_opportunity_booking_document(opp, attachment_url, booking_name=booking.name)

	opp.insert()
	sync_opportunity_from_submitted_booking(booking, opp.name)

	if booking.meta.has_field(OPPORTUNITY_SOURCE_FIELD):
		frappe.db.set_value(
			"Booking Confirmation",
			booking.name,
			OPPORTUNITY_SOURCE_FIELD,
			opp.name,
			update_modified=False,
		)

	return opp.name
