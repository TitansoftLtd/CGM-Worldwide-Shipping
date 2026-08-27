# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Air Waybill controller and its Opportunity-sync logic.

Mirrors the Bill of Lading flow for air freight: an Air Waybill branches a CRM
Opportunity (carrying the customer, shipment type, description and the AWB
document) and an Opportunity surfaces its Air Waybill under Connections. Air
freight has no container manifest. Quantity is derived from packages the same
way LCL does (package count + package type), not from a container table.
"""

import frappe
from frappe.model.document import Document

from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
	ensure_document_types,
	get_document_type_link_name,
	get_opportunity_documents_field,
	prepend_clients_document_row,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment import (
	copy_opportunity_scalars_to_project,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	apply_awb_fields_to_doc,
	awb_propagation_payload,
	OPPORTUNITY_TO_AWB_FIELDS,
)

# Air Waybill -> Opportunity (back-link on this doctype) and Opportunity -> AWB.
OPPORTUNITY_SOURCE_FIELD = "linked_opportunity"
OPPORTUNITY_AWB_FIELD = "custom_air_waybill"
DOCUMENT_TYPE_CODE = "AWB"


class AirWaybill(Document):
	def autoname(self):
		# Name by the Air Waybill number (naming_rule: "By script").
		if not self.air_waybill:
			frappe.throw(frappe._("Air Waybill number is required"))
		self.name = self.air_waybill

	def validate(self):
		sanitize_air_waybill_linked_opportunity(self)

	def on_update(self):
		# Sync after the AWB row exists — validate runs before insert and cannot
		# set Opportunity.custom_air_waybill (Link) yet.
		if self.get(OPPORTUNITY_SOURCE_FIELD):
			sync_opportunity_from_awb(self, allow_draft=True)

	def on_submit(self):
		"""Keep the linked Opportunity aligned once the Air Waybill is submitted."""
		opportunity = sync_opportunity_from_awb(self, allow_draft=False)
		if opportunity:
			sync_linked_project_from_awb(self, opportunity)


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
def _set_opp_value(opp, fieldname: str, value) -> bool:
	"""Set Opportunity field when source value is present and differs."""
	if not fieldname or not opp.meta.has_field(fieldname):
		return False
	if value in (None, ""):
		return False
	if opp.get(fieldname) == value:
		return False
	opp.set(fieldname, value)
	return True


def apply_awb_fields_to_opportunity(opp, awb_doc) -> bool:
	"""Copy AWB fields onto Opportunity. Returns True if anything changed."""
	changed = False

	if awb_doc.name and frappe.db.exists("Air Waybill", awb_doc.name):
		if _set_opp_value(opp, OPPORTUNITY_AWB_FIELD, awb_doc.name):
			changed = True

	if apply_awb_fields_to_doc(opp, awb_doc):
		changed = True

	return changed


def sync_opportunity_from_awb(
	awb_doc,
	opportunity: str | None = None,
	*,
	allow_draft: bool = False,
) -> str | None:
	"""Link AWB data back onto the source Opportunity."""
	opportunity = opportunity or awb_doc.get(OPPORTUNITY_SOURCE_FIELD)
	if not is_valid_opportunity_link(opportunity):
		return None
	if not allow_draft and awb_doc.docstatus != 1:
		return None

	opp = frappe.get_doc("Opportunity", opportunity)
	changed = apply_awb_fields_to_opportunity(opp, awb_doc)

	attachment_url = awb_doc.get("attach_airwaybill")
	clients_field = get_opportunity_documents_field()
	if (
		awb_doc.docstatus == 1
		and attachment_url
		and clients_field
		and opp.meta.has_field(clients_field)
	):
		if prepend_opportunity_awb_document(opp, attachment_url, awb_name=awb_doc.name):
			changed = True

	if changed:
		opp.save(ignore_permissions=True)

	return opportunity


def sync_opportunity_from_submitted_awb(awb_doc, opportunity: str | None = None) -> str | None:
	"""Backward-compatible alias used by submit / payload helpers."""
	return sync_opportunity_from_awb(awb_doc, opportunity, allow_draft=False)


def _scalar_seed_value(value):
	if value in (None, ""):
		return None
	return value


def build_awb_seed_from_opportunity(opp) -> dict:
	"""Prefill payload when creating an Air Waybill from Opportunity."""
	seed: dict = {}
	if opp.name and is_valid_opportunity_link(opp.name):
		seed["linked_opportunity"] = opp.name

	if opp.opportunity_from == "Customer" and opp.get("party_name"):
		seed["customer"] = opp.party_name

	if opp.get("custom_shipment_type"):
		seed["shipment_type"] = opp.get("custom_shipment_type")

	for src, dest in OPPORTUNITY_TO_AWB_FIELDS:
		if not opp.meta.has_field(src):
			continue
		value = _scalar_seed_value(opp.get(src))
		if value is not None:
			seed[dest] = value

	return seed


def sync_linked_project_from_awb(awb_doc, opportunity: str) -> str | None:
	"""When a Project already exists, push AWB / Opportunity values onto it."""
	if not opportunity or not frappe.get_meta("Project").has_field("custom_source_opportunity"):
		return None

	project_name = frappe.db.get_value(
		"Project", {"custom_source_opportunity": opportunity}, "name"
	)
	if not project_name:
		return None

	frappe.has_permission("Project", ptype="write", doc=project_name, throw=True)
	project = frappe.get_doc("Project", project_name)
	opp = frappe.get_doc("Opportunity", opportunity)
	changed = False

	if project.meta.has_field(OPPORTUNITY_AWB_FIELD) and project.get(OPPORTUNITY_AWB_FIELD) != awb_doc.name:
		project.set(OPPORTUNITY_AWB_FIELD, awb_doc.name)
		changed = True

	if apply_awb_fields_to_doc(project, awb_doc):
		changed = True

	if copy_opportunity_scalars_to_project(project, opp):
		changed = True

	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		sync_project_documents_from_opportunity,
	)

	sync_project_documents_from_opportunity(project, opp)

	project.flags.ignore_validate = True
	project.save(ignore_permissions=True)
	return project_name


def prepend_opportunity_awb_document(opp_doc, attachment_url, awb_name=None) -> bool:
	"""Insert the AWB row as the first Clients Documents entry on the Opportunity."""
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
		remarks=frappe._("From submitted Air Waybill {0}").format(awb_name or ""),
	)


# ─── Whitelisted API ──────────────────────────────────────────────────────────
@frappe.whitelist()
def get_awb_seed_for_opportunity(opportunity: str | None = None) -> dict:
	"""Return AWB prefill fields from the linked Opportunity.

	Used by + Add Air Waybill so users never re-enter intake shipment data.
	"""
	if not is_valid_opportunity_link(opportunity):
		return {}

	frappe.has_permission("Opportunity", ptype="read", doc=opportunity, throw=True)
	opp = frappe.get_doc("Opportunity", opportunity)
	return build_awb_seed_from_opportunity(opp)


@frappe.whitelist()
def get_awb_fields_for_opportunity(air_waybill: str | None = None) -> dict:
	"""Return AWB field payload for Opportunity client/server refresh."""
	if not air_waybill or not frappe.db.exists("Air Waybill", air_waybill):
		return {}
	frappe.has_permission("Air Waybill", ptype="read", doc=air_waybill, throw=True)
	doc = frappe.get_doc("Air Waybill", air_waybill)
	return awb_propagation_payload(doc)


@frappe.whitelist()
def get_awb_submit_payload(awb_name: str, opportunity: str | None = None) -> dict:
	"""Return AWB link metadata for applying on the Opportunity form after submit."""
	if not awb_name or not frappe.db.exists("Air Waybill", awb_name):
		frappe.throw("Air Waybill not found", frappe.DoesNotExistError)

	frappe.has_permission("Air Waybill", ptype="read", doc=awb_name, throw=True)
	doc = frappe.get_doc("Air Waybill", awb_name)
	if doc.docstatus != 1:
		frappe.throw("Air Waybill must be submitted first.")

	linked_opportunity = sync_opportunity_from_submitted_awb(doc, opportunity)
	payload = awb_propagation_payload(doc)
	payload["opportunity"] = linked_opportunity
	payload["attachment"] = doc.get("attach_airwaybill") or ""
	payload["document_type"] = get_document_type_link_name(DOCUMENT_TYPE_CODE)
	return payload


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

	if opp.meta.has_field("custom_consignee"):
		opp.set(
			"custom_consignee",
			frappe.db.get_value("Customer", customer, "customer_name") or customer,
		)

	apply_awb_fields_to_opportunity(opp, awb)

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
