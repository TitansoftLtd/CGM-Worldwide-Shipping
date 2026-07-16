"""Opportunity as Shipment Intake & Document Verification — config-driven start flow.

Behaviour is driven by Shipment Type master (transport_documents,
required_documents, task_flow_key). No shipment-type name hardcoding.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	container_tracking_mode_for_shipment_type,
	get_shipment_type_record,
)
from cgm_shipping.cgm_worldwide_shipping.services.shipment_type_service import (
	PRIMARY_DOC_TO_DOCTYPE,
	PRIMARY_DOC_TO_OPP_FIELD,
	START_GATE_ALTERNATES,
	TRANSPORT_DOC_TO_OPP_FIELD,
	get_allowed_transport_documents,
	resolve_primary_transport_document,
)


def get_transport_documents_with_links(opportunity) -> list[dict]:
	"""Allowed transport documents enriched with current Opportunity link values."""
	allowed = get_allowed_transport_documents(opportunity.get("custom_shipment_type"))
	out: list[dict] = []
	for item in allowed:
		field = item.get("opp_field")
		linked_name = None
		if field and opportunity.meta.has_field(field):
			linked_name = opportunity.get(field)
		out.append({**item, "linked_name": linked_name or None})
	return out


def has_any_transport_document(opportunity) -> bool:
	for item in get_transport_documents_with_links(opportunity):
		if item.get("linked_name"):
			return True
	for field in TRANSPORT_DOC_TO_OPP_FIELD.values():
		if opportunity.meta.has_field(field) and opportunity.get(field):
			return True
	return False


def has_required_transport_documents(opportunity) -> bool:
	"""True when Start Shipment transport gate is satisfied.

	Bill of Lading and Booking Confirmation are interchangeable: either one is
	enough when both are allowed on the Shipment Type (whichever arrives first).
	Other required documents (e.g. Air Waybill) still use an OR within their set.
	"""
	linked = get_transport_documents_with_links(opportunity)
	if not linked:
		return has_any_transport_document(opportunity)

	alternates = [
		item for item in linked if item.get("transport_document") in START_GATE_ALTERNATES
	]
	if alternates:
		return any(item.get("linked_name") for item in alternates)

	required = [item for item in linked if item.get("is_required_for_start")]
	if not required:
		allowed = get_allowed_transport_documents(opportunity.get("custom_shipment_type"))
		if allowed:
			return has_any_transport_document(opportunity)
		return True
	return any(item.get("linked_name") for item in required)


def has_primary_transport_document(opportunity) -> bool:
	"""Backward-compatible alias — start-gate transport document(s) must be linked."""
	return has_required_transport_documents(opportunity)


def allocate_opportunity_batch_no() -> str:
	"""Increment CGM Shipping Settings last_batch_no and return the new batch as a string."""
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return "1"

	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field("last_batch_no"):
		return "1"

	# tabSingles columns are doctype / field / value (no name column).
	frappe.db.sql(
		"""
		SELECT `value` FROM `tabSingles`
		WHERE `doctype` = %s AND `field` = %s
		FOR UPDATE
		""",
		("CGM Shipping Settings", "last_batch_no"),
	)
	last = cint(frappe.db.get_single_value("CGM Shipping Settings", "last_batch_no") or 0)
	new_batch = last + 1
	frappe.db.set_single_value("CGM Shipping Settings", "last_batch_no", new_batch)
	return str(new_batch)


def assign_opportunity_batch_on_insert(doc, _method=None) -> None:
	"""Opportunity batch is assigned from FCL Booking Confirmation / Bill of Lading.

	Do not use the global Settings counter here — FCL batches are per
	Customer + Shipment Type + Derived Quantity.
	"""
	return


def get_shipment_type_flags(shipment_type: str | None) -> dict:
	"""Read Shipment Type master flags for client-side field visibility (no hardcoded names)."""
	row = get_shipment_type_record(shipment_type)
	if not row:
		return {}

	mode = (row.get("default_mode_of_transport") or "").strip()
	primary = resolve_primary_transport_document(row)
	transport_documents = get_allowed_transport_documents(shipment_type)

	return {
		"is_outbound": bool(row.get("is_outbound")),
		"uses_export_documents": bool(row.get("uses_export_documents")),
		"uses_transit_documents": bool(row.get("uses_transit_documents")),
		"uses_destination_entry": bool(row.get("uses_destination_entry")),
		"uses_container_tracking": bool(row.get("uses_container_tracking")),
		"default_mode_of_transport": mode,
		"task_flow_key": (row.get("task_flow_key") or "").strip(),
		"primary_transport_document": primary,
		"primary_transport_doctype": PRIMARY_DOC_TO_DOCTYPE.get(primary),
		"primary_transport_opp_field": PRIMARY_DOC_TO_OPP_FIELD.get(primary),
		"transport_documents": transport_documents,
		"container_tracker_mode": container_tracking_mode_for_shipment_type(shipment_type),
	}


@frappe.whitelist()
def get_shipment_type_flags_for_doc(shipment_type: str | None = None) -> dict:
	return get_shipment_type_flags(shipment_type)


def project_type_for_shipment_type(shipment_type: str | None) -> str | None:
	"""Map Shipment Type → Project.project_type via container_tracker_mode."""
	return container_tracking_mode_for_shipment_type(shipment_type)


def apply_project_type_from_shipment_type(project, shipment_type: str | None = None) -> None:
	st = shipment_type or project.get("custom_shipment_type")
	if not st or not project.meta.has_field("project_type"):
		return
	project_type = project_type_for_shipment_type(st)
	if project_type:
		project.project_type = project_type


def opportunity_to_project_field_pairs() -> tuple[tuple[str, str], ...]:
	"""Scalar fields copied Opportunity → Project on create."""
	return (
		("custom_eta", "custom_eta"),
		("custom_etd", "custom_etd"),
		("custom_shipping_line", "custom_shipping_line"),
		("custom_shipping_order_ref", "custom_shipping_order_ref"),
		("custom_booking_ref", "custom_booking_ref"),
		("custom_handling_agent", "custom_handling_agent"),
		("custom_delivery_destination", "custom_final_destination"),
		("custom_booking_confirmation", "custom_booking_confirmation"),
	)


def get_required_intake_documents(shipment_type: str | None) -> list[dict]:
	"""Mandatory Document Type rows from Shipment Type.required_documents."""
	if not shipment_type or not frappe.db.exists("Shipment Type", shipment_type):
		return []
	meta = frappe.get_meta("Shipment Type")
	if not meta.has_field("required_documents"):
		return []

	st = frappe.get_doc("Shipment Type", shipment_type)
	out: list[dict] = []
	for row in st.get("required_documents") or []:
		if not row.get("document_type"):
			continue
		if row.get("is_mandatory") in (0, "0", False):
			continue
		out.append(
			{
				"document_type": row.document_type,
				"notes": row.get("notes") or "",
			}
		)
	return out


def evaluate_start_shipment_readiness(opportunity_name: str) -> dict:
	"""Check primary transport doc + required documents uploaded & verified."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		document_types_match,
		get_opportunity_documents_field,
		is_shipment_document_verified,
		primary_attachment,
	)

	frappe.has_permission("Opportunity", ptype="read", doc=opportunity_name, throw=True)
	opp = frappe.get_doc("Opportunity", opportunity_name)
	shipment_type = opp.get("custom_shipment_type")
	flags = get_shipment_type_flags(shipment_type)

	blockers: list[str] = []
	missing_docs: list[str] = []
	unverified_docs: list[str] = []

	if not shipment_type:
		blockers.append(_("Select a Shipment Type before starting the shipment."))

	transport_documents = get_transport_documents_with_links(opp)
	if not has_required_transport_documents(opp):
		alternates = [
			item["transport_document"]
			for item in transport_documents
			if item.get("transport_document") in START_GATE_ALTERNATES
		]
		if len(alternates) >= 2:
			blockers.append(
				_("Link Bill of Lading or Booking Confirmation (whichever was provided first).")
			)
		else:
			missing_transport = [
				item["transport_document"]
				for item in transport_documents
				if item.get("is_required_for_start") and not item.get("linked_name")
			]
			if missing_transport:
				blockers.append(
					_("Link required transport document(s): {0}").format(
						", ".join(missing_transport)
					)
				)
			elif transport_documents:
				blockers.append(_("Attach at least one transport document to this shipment."))

	docs_field = get_opportunity_documents_field()
	uploaded_rows = list(opp.get(docs_field) or []) if docs_field else []

	for req in get_required_intake_documents(shipment_type):
		doc_type = req["document_type"]
		matched = [
			row
			for row in uploaded_rows
			if document_types_match(row.get("document_type"), doc_type)
		]
		with_file = [row for row in matched if primary_attachment(row)]
		if not with_file:
			missing_docs.append(doc_type)
			continue
		if not any(is_shipment_document_verified(row) for row in with_file):
			unverified_docs.append(doc_type)

	if missing_docs:
		blockers.append(
			_("Upload required document(s): {0}").format(", ".join(missing_docs))
		)
	if unverified_docs:
		blockers.append(
			_("Verify required document(s): {0}").format(", ".join(unverified_docs))
		)

	existing_project = None
	if frappe.get_meta("Project").has_field("custom_source_opportunity"):
		existing_project = frappe.db.get_value(
			"Project", {"custom_source_opportunity": opportunity_name}, "name"
		)

	return {
		"ok": not blockers,
		"blockers": blockers,
		"missing_documents": missing_docs,
		"unverified_documents": unverified_docs,
		"primary_transport_document": flags.get("primary_transport_document"),
		"primary_transport_doctype": flags.get("primary_transport_doctype"),
		"primary_transport_opp_field": flags.get("primary_transport_opp_field"),
		"transport_documents": transport_documents,
		"primary_linked": has_any_transport_document(opp),
		"transport_docs_linked": has_any_transport_document(opp),
		"required_transport_linked": has_required_transport_documents(opp),
		"existing_project": existing_project,
		"workflow_state": opp.get("workflow_state"),
	}


@frappe.whitelist()
def get_start_shipment_readiness(opportunity: str) -> dict:
	return evaluate_start_shipment_readiness(opportunity)


@frappe.whitelist()
def start_shipment_from_opportunity(opportunity: str) -> str:
	"""Gate + create Project (Start Shipment)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		APPROVED_WORKFLOW_STATE,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import (
		create_project_from_opportunity,
	)

	readiness = evaluate_start_shipment_readiness(opportunity)
	if readiness.get("existing_project"):
		return readiness["existing_project"]

	if not readiness["ok"]:
		frappe.throw(
			"<br>".join(readiness["blockers"]),
			title=_("Cannot Start Shipment"),
		)

	opp = frappe.get_doc("Opportunity", opportunity)
	if opp.get("workflow_state") and opp.workflow_state != APPROVED_WORKFLOW_STATE:
		frappe.throw(
			_(
				"Opportunity must be <b>Approved</b> before starting the shipment "
				"(current: {0})."
			).format(opp.workflow_state)
		)

	return create_project_from_opportunity(opportunity)


def seed_required_documents_on_opportunity(doc, _method=None) -> None:
	"""Ensure Clients Documents has a row for each Shipment Type required document."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		document_types_match,
		get_opportunity_documents_field,
	)

	shipment_type = doc.get("custom_shipment_type")
	if not shipment_type:
		return

	docs_field = get_opportunity_documents_field()
	if not docs_field or not doc.meta.has_field(docs_field):
		return

	required = get_required_intake_documents(shipment_type)
	if not required:
		return

	existing = list(doc.get(docs_field) or [])
	for req in required:
		doc_type = req["document_type"]
		if any(document_types_match(row.get("document_type"), doc_type) for row in existing):
			continue
		row = doc.append(docs_field, {"document_type": doc_type, "status": "Missing"})
		existing.append(row)
