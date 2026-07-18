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
from cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch import (
	allocate_fcl_batch_for_doc,
	derived_quantity_from_booking,
	is_lcl_cargo_type,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	apply_shipment_type_profile_to_doc,
	get_cargo_type_field,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import coerce_numeric_fields

OPPORTUNITY_SOURCE_FIELD = "linked_opportunity"
OPPORTUNITY_BOOKING_FIELD = "custom_booking_confirmation"
OPPORTUNITY_REQUESTED_CARGO_FIELD = "custom_requested_cargo_quantity"
DOCUMENT_TYPE_CODE = "BOOKING"

# Booking Confirmation → Opportunity scalar fields (overwrite when source has a value).
BOOKING_TO_OPPORTUNITY_FIELDS = (
	("shipping_line", "custom_shipping_line"),
	("vessel", "custom_vessel"),
	("etd", "custom_etd"),
	("eta", "custom_eta"),
	("booking_number", "custom_booking_ref"),
	("booking_number", "custom_shipping_order_ref"),
	("commodity", "custom_description_of_goods"),
	("client_ref", "custom_client_refrence_no"),
	("gross_weight", "custom_gross_weight"),
	("net_weight", "custom_weight_nw"),
	("weight_uom", "custom_weight_uom_"),
	("port_of_loading", "custom_port_of_loading"),
	("port_of_discharge", "custom_port_of_discharge"),
	("voyage_number", "custom_voyage_number"),
	("cargo_cut_off", "custom_cargo_cut_off"),
	("number_of_packages", "custom_number_of_packages"),
	("package_type", "custom_package_type"),
	("batch_no", "custom_batch_no"),
)


class BookingConfirmation(Document):
	def validate(self):
		coerce_numeric_fields(self, ("gross_weight", "net_weight"))
		sanitize_booking_linked_opportunity(self)
		apply_booking_quantity_and_batch(self)

	def on_update(self):
		# Keep linked Opportunity in sync while the booking is being filled (before submit).
		if self.get(OPPORTUNITY_SOURCE_FIELD):
			sync_opportunity_from_booking(self, allow_draft=True)

	def on_submit(self):
		opportunity = sync_opportunity_from_booking(self, allow_draft=False)
		if opportunity:
			from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
				sync_linked_project_documents_from_opportunity,
			)

			sync_linked_project_documents_from_opportunity(opportunity)


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


def _set_opp_value(opp, fieldname: str, value) -> bool:
	"""Set Opportunity field when source value is present and differs."""
	if not fieldname or not opp.meta.has_field(fieldname):
		return False
	if value in (None, ""):
		return False

	df = opp.meta.get_field(fieldname)
	if df and df.fieldtype in ("Float", "Currency", "Percent", "Int"):
		try:
			value = float(str(value).replace(",", "").strip())
		except (TypeError, ValueError):
			return False
		if df.fieldtype == "Int":
			value = int(value)

	if opp.get(fieldname) == value:
		return False
	opp.set(fieldname, value)
	# Keep legacy duplicate Net Weight column in sync when present.
	if fieldname == "custom_weight_nw" and opp.meta.has_field("custom_net_weight"):
		opp.set("custom_net_weight", value)
	return True


def apply_booking_quantity_and_batch(doc) -> None:
	"""Set derived quantity and FCL batch on Booking Confirmation."""
	cargo_type = doc.get("requested_cargo_type")
	if is_lcl_cargo_type(cargo_type):
		# LCL uses packages — not the FCL batch sequence.
		pkgs = (doc.get("number_of_packages") or "").strip()
		ptype = (doc.get("package_type") or "").strip()
		if doc.meta.has_field("quantity"):
			doc.quantity = f"{pkgs} {ptype}".strip() if pkgs or ptype else ""
		if doc.meta.has_field("batch_no"):
			doc.batch_no = None
		return

	derived = derived_quantity_from_booking(doc)
	if not derived:
		if doc.meta.has_field("batch_no"):
			doc.batch_no = None
		return

	allocate_fcl_batch_for_doc(
		doc,
		cargo_type_field="requested_cargo_type",
		derived_quantity=derived,
	)


def summarize_booking_quantity(booking_doc) -> str:
	"""Build a quantity summary from FCL requested rows or LCL packages."""
	cargo_type = (booking_doc.get("requested_cargo_type") or "").strip()
	if is_lcl_cargo_type(cargo_type):
		pkgs = (booking_doc.get("number_of_packages") or "").strip()
		ptype = (booking_doc.get("package_type") or "").strip()
		if pkgs and ptype:
			return f"{pkgs} {ptype}"
		return pkgs or ptype

	return derived_quantity_from_booking(booking_doc)


def requested_cargo_quantity_rows(booking_doc) -> list[dict]:
	"""Serialize Requested Containers child rows for payloads / Opportunity copy."""
	rows: list[dict] = []
	for row in booking_doc.get("requested_cargo_quantity") or []:
		size = (row.get("cargo_size") or "").strip()
		qty = str(row.get("quantity") or "").strip()
		if not size and not qty:
			continue
		rows.append({"cargo_size": size, "quantity": qty})
	return rows


def copy_requested_cargo_quantity_to_opportunity(opp, booking_doc) -> bool:
	"""Copy FCL requested-cargo rows onto Opportunity; clear them for LCL."""
	if not opp.meta.has_field(OPPORTUNITY_REQUESTED_CARGO_FIELD):
		return False

	cargo_type = (booking_doc.get("requested_cargo_type") or "").strip()
	rows = requested_cargo_quantity_rows(booking_doc)
	# LCL has packages instead of container request rows.
	if cargo_type == "LCL":
		new_rows = []
	else:
		new_rows = rows

	existing = [
		{
			"cargo_size": (row.get("cargo_size") or "").strip(),
			"quantity": str(row.get("quantity") or "").strip(),
		}
		for row in opp.get(OPPORTUNITY_REQUESTED_CARGO_FIELD) or []
	]
	if existing == new_rows:
		return False

	opp.set(OPPORTUNITY_REQUESTED_CARGO_FIELD, [])
	for row in new_rows:
		opp.append(OPPORTUNITY_REQUESTED_CARGO_FIELD, row)
	return True


def apply_booking_fields_to_opportunity(opp, booking_doc) -> bool:
	"""Copy shipped booking fields onto Opportunity. Returns True if anything changed."""
	changed = False

	if _set_opp_value(opp, OPPORTUNITY_BOOKING_FIELD, booking_doc.name):
		changed = True

	if apply_shipment_type_profile_to_doc(opp, booking_doc.get("shipment_type")):
		changed = True

	cargo_type = booking_doc.get("requested_cargo_type")
	cargo_field = get_cargo_type_field(opp.meta)
	if cargo_field and _set_opp_value(opp, cargo_field, cargo_type):
		changed = True

	for src, dest in BOOKING_TO_OPPORTUNITY_FIELDS:
		if _set_opp_value(opp, dest, booking_doc.get(src)):
			changed = True

	quantity = summarize_booking_quantity(booking_doc)
	if _set_opp_value(opp, "custom_quantity", quantity):
		changed = True

	if copy_requested_cargo_quantity_to_opportunity(opp, booking_doc):
		changed = True

	return changed


def booking_propagation_payload(booking_doc) -> dict:
	"""Fields for client-side Opportunity apply after Booking submit redirect."""
	profile_changed = False
	shipment_type = booking_doc.get("shipment_type")
	link_name = None
	default_mode = None
	if shipment_type:
		from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
			canonical_shipment_type_link,
			shipment_type_profile,
		)

		link_name = canonical_shipment_type_link(shipment_type)
		profile = shipment_type_profile(link_name or shipment_type) if shipment_type else None
		default_mode = (profile or {}).get("default_mode_of_transport")
		profile_changed = bool(link_name)

	payload = {
		"booking_name": booking_doc.name,
		"attachment": booking_doc.get("attach_booking") or "",
		"document_type": get_document_type_link_name(DOCUMENT_TYPE_CODE),
		"shipment_type": link_name or shipment_type,
		"default_mode_of_transport": default_mode,
		"booking_number": booking_doc.get("booking_number"),
		"shipping_line": booking_doc.get("shipping_line"),
		"vessel": booking_doc.get("vessel"),
		"etd": booking_doc.get("etd"),
		"eta": booking_doc.get("eta"),
		"client_ref": booking_doc.get("client_ref"),
		"commodity": booking_doc.get("commodity"),
		"requested_cargo_type": booking_doc.get("requested_cargo_type"),
		"gross_weight": booking_doc.get("gross_weight"),
		"net_weight": booking_doc.get("net_weight"),
		"weight_uom": booking_doc.get("weight_uom"),
		"quantity": summarize_booking_quantity(booking_doc) or booking_doc.get("quantity"),
		"batch_no": booking_doc.get("batch_no"),
		"requested_cargo_quantity": requested_cargo_quantity_rows(booking_doc),
		"port_of_loading": booking_doc.get("port_of_loading"),
		"port_of_discharge": booking_doc.get("port_of_discharge"),
		"voyage_number": booking_doc.get("voyage_number"),
		"cargo_cut_off": booking_doc.get("cargo_cut_off"),
		"number_of_packages": booking_doc.get("number_of_packages"),
		"package_type": booking_doc.get("package_type"),
	}
	# Keep linter calm if profile helpers unused beyond values above.
	_ = profile_changed
	return payload


def sync_opportunity_from_booking(
	booking_doc,
	opportunity: str | None = None,
	*,
	allow_draft: bool = False,
) -> str | None:
	"""Copy Booking Confirmation fields onto the linked Opportunity.

	``allow_draft=True`` syncs while the booking is still being prepared so
	Opportunity mirrors weights / requested cargo before submit.
	"""
	opportunity = opportunity or booking_doc.get(OPPORTUNITY_SOURCE_FIELD)
	if not is_valid_opportunity_link(opportunity):
		return None
	if not allow_draft and booking_doc.docstatus != 1:
		return None

	opp = frappe.get_doc("Opportunity", opportunity)
	changed = apply_booking_fields_to_opportunity(opp, booking_doc)

	attachment_url = booking_doc.get("attach_booking")
	clients_field = get_opportunity_documents_field()
	if (
		booking_doc.docstatus == 1
		and attachment_url
		and clients_field
		and opp.meta.has_field(clients_field)
	):
		if prepend_opportunity_booking_document(opp, attachment_url, booking_name=booking_doc.name):
			changed = True

	if changed:
		opp.save(ignore_permissions=True)

	return opportunity


def sync_opportunity_from_submitted_booking(booking_doc, opportunity: str | None = None) -> str | None:
	"""Backward-compatible alias used by submit / payload helpers."""
	return sync_opportunity_from_booking(booking_doc, opportunity, allow_draft=False)


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
def get_booking_fields_for_opportunity(booking_confirmation: str | None = None) -> dict:
	"""Return booking field payload for Opportunity client/server refresh."""
	if not booking_confirmation or not frappe.db.exists("Booking Confirmation", booking_confirmation):
		return {}
	frappe.has_permission("Booking Confirmation", ptype="read", doc=booking_confirmation, throw=True)
	doc = frappe.get_doc("Booking Confirmation", booking_confirmation)
	return booking_propagation_payload(doc)


@frappe.whitelist()
def get_booking_submit_payload(booking_name: str, opportunity: str | None = None) -> dict:
	if not booking_name or not frappe.db.exists("Booking Confirmation", booking_name):
		frappe.throw("Booking Confirmation not found", frappe.DoesNotExistError)

	frappe.has_permission("Booking Confirmation", ptype="read", doc=booking_name, throw=True)
	doc = frappe.get_doc("Booking Confirmation", booking_name)
	if doc.docstatus != 1:
		frappe.throw("Booking Confirmation must be submitted first.")

	linked_opportunity = sync_opportunity_from_submitted_booking(doc, opportunity)
	payload = booking_propagation_payload(doc)
	payload["opportunity"] = linked_opportunity
	return payload


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

	if opp.meta.has_field("custom_consignee"):
		opp.set(
			"custom_consignee",
			frappe.db.get_value("Customer", customer, "customer_name") or customer,
		)

	apply_booking_fields_to_opportunity(opp, booking)

	attachment_url = booking.get("attach_booking")
	clients_field = get_opportunity_documents_field()
	if attachment_url and clients_field and opp.meta.has_field(clients_field):
		prepend_opportunity_booking_document(opp, attachment_url, booking_name=booking.name)

	opp.insert()

	if booking.meta.has_field(OPPORTUNITY_SOURCE_FIELD):
		frappe.db.set_value(
			"Booking Confirmation",
			booking.name,
			OPPORTUNITY_SOURCE_FIELD,
			opp.name,
			update_modified=False,
		)

	return opp.name
