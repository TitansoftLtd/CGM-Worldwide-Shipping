"""Opportunity Shipment Intake wizard — stage sync and UI context.

Form layout / disclosure (depends_on, field order, labels, Property Setters)
lives in ``custom/opportunity.json`` (sync_on_migrate). This module only
implements business rules:

* intake — Customer + Shipment Type + Client Reference only
* awaiting_primary — saved; user must create/link primary transport document
* documents — primary doc linked; transport info + client documents + containers
* authorization — required documents verified; approve / start shipment
"""

from __future__ import annotations

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment import (
	evaluate_start_shipment_readiness,
	get_shipment_type_flags,
	has_any_transport_document,
	transport_documents_deferred,
)

STAGE_INTAKE = "intake"
STAGE_AWAITING_PRIMARY = "awaiting_primary"  # Shipment dashboard — add transport documents
STAGE_DOCUMENTS = "documents"
STAGE_AUTHORIZATION = "authorization"

WIZARD_STEPS = (
	(STAGE_INTAKE, "1. Shipment Intake", "Customer & shipment type"),
	(STAGE_AWAITING_PRIMARY, "2. Transport Documents", "Add documents as they arrive"),
	(STAGE_DOCUMENTS, "3. Documents", "Transport info & verification"),
	(STAGE_AUTHORIZATION, "4. Start Shipment", "Approve & create project"),
)


def sync_opportunity_intake_stage(doc) -> None:
	"""Set hidden stage flags used by depends_on expressions on the form."""
	if not doc.meta.has_field("custom_intake_stage"):
		return

	if not (doc.get("custom_shipment_type") or "").strip():
		doc.custom_intake_stage = STAGE_INTAKE
		if doc.meta.has_field("custom_primary_doc_linked"):
			doc.custom_primary_doc_linked = 0
		if doc.meta.has_field("custom_uses_container_tracking"):
			doc.custom_uses_container_tracking = 0
		return

	flags = get_shipment_type_flags(doc.get("custom_shipment_type"))
	if doc.meta.has_field("custom_uses_container_tracking"):
		doc.custom_uses_container_tracking = int(bool(flags.get("uses_container_tracking")))
	mode = (flags.get("default_mode_of_transport") or "").strip()
	if mode and doc.meta.has_field("custom_mode_of_transport"):
		if not doc.get("custom_mode_of_transport") or doc.has_value_changed("custom_shipment_type"):
			doc.custom_mode_of_transport = mode

	primary_linked = has_any_transport_document(doc) or transport_documents_deferred(doc)
	if doc.meta.has_field("custom_primary_doc_linked"):
		doc.custom_primary_doc_linked = int(primary_linked)

	if primary_linked and doc.meta.has_field("custom_uses_container_tracking"):
		if doc.get("custom_bill_of_lading") or flags.get("uses_container_tracking"):
			doc.custom_uses_container_tracking = 1

	if not doc.name or str(doc.name).startswith("new-"):
		if not (doc.get("custom_shipment_type") or "").strip():
			doc.custom_intake_stage = STAGE_INTAKE
		else:
			doc.custom_intake_stage = STAGE_AWAITING_PRIMARY
		return

	if not primary_linked:
		doc.custom_intake_stage = STAGE_AWAITING_PRIMARY
		return

	readiness = evaluate_start_shipment_readiness(doc.name)
	if readiness.get("ok"):
		doc.custom_intake_stage = STAGE_AUTHORIZATION
	else:
		doc.custom_intake_stage = STAGE_DOCUMENTS


def prepare_opportunity_intake(doc, _method=None) -> None:
	"""Defaults for new shipment intake records."""
	doc.opportunity_from = "Customer"
	if doc.meta.has_field("custom_intake_stage"):
		doc.custom_intake_stage = STAGE_INTAKE
	# Clear site Country defaults (e.g. Kenya) — user selects these manually.
	for fieldname in ("custom_country_of_origin", "custom_delivery_destination"):
		if doc.meta.has_field(fieldname) and doc.is_new():
			doc.set(fieldname, None)
	sync_opportunity_intake_stage(doc)


def validate_opportunity_intake(doc, _method=None) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import coerce_numeric_fields

	coerce_numeric_fields(
		doc,
		("custom_gross_weight", "custom_net_weight"),
		empty_as_zero=False,
	)

	if not doc.opportunity_from:
		doc.opportunity_from = "Customer"
	if not doc.party_name:
		frappe.throw(_("Customer is required"), title=_("Shipment Intake"))
	if not (doc.get("custom_shipment_type") or "").strip():
		frappe.throw(_("Shipment Type is required"), title=_("Shipment Intake"))
	sync_consignee_from_customer(doc)


def sync_consignee_from_customer(doc, _method=None) -> None:
	"""Keep Consignee aligned with the selected Customer."""
	if not doc.get("party_name") or not doc.meta.has_field("custom_consignee"):
		return
	if (doc.get("opportunity_from") or "Customer") != "Customer":
		return

	customer_label = (
		frappe.db.get_value("Customer", doc.party_name, "customer_name") or doc.party_name
	)
	if not doc.get("custom_consignee") or doc.has_value_changed("party_name"):
		doc.custom_consignee = customer_label


def sync_opportunity_intake_on_save(doc, _method=None) -> None:
	sync_opportunity_intake_stage(doc)


def _wizard_step_class(current: str, step: str, completed_steps: set[str]) -> str:
	if step == current:
		return "cgm-wizard-step is-active"
	if step in completed_steps:
		return "cgm-wizard-step is-done"
	return "cgm-wizard-step"


def build_intake_wizard_html(stage: str, readiness: dict | None = None) -> str:
	flags = readiness or {}
	completed: set[str] = set()
	if stage != STAGE_INTAKE:
		completed.add(STAGE_INTAKE)
	if stage in (STAGE_DOCUMENTS, STAGE_AUTHORIZATION):
		completed.add(STAGE_AWAITING_PRIMARY)
	if stage == STAGE_AUTHORIZATION:
		completed.add(STAGE_DOCUMENTS)

	parts = ['<div class="cgm-shipment-intake-wizard">']
	for key, title, subtitle in WIZARD_STEPS:
		cls = _wizard_step_class(stage, key, completed)
		parts.append(
			f'<div class="{cls}"><div class="cgm-wizard-step-title">{_(title)}</div>'
			f'<div class="cgm-wizard-step-sub">{_(subtitle)}</div></div>'
		)
	parts.append("</div>")

	message = ""
	if stage == STAGE_INTAKE:
		message = _("Select the customer and shipment type, then save to continue.")
	elif stage == STAGE_AWAITING_PRIMARY:
		message = _(
			"Use <b>Transport Documents</b> below to add Bill of Lading, Booking Confirmation, "
			"or other transport documents as they become available."
		)
	elif stage == STAGE_DOCUMENTS:
		blockers = flags.get("blockers") or []
		if blockers:
			message = "<br>".join(blockers)
		else:
			message = _("Upload and verify all required client documents, then submit for approval.")
	elif stage == STAGE_AUTHORIZATION:
		state = (flags.get("workflow_state") or "").strip()
		if flags.get("transport_docs_deferred"):
			message = _(
				"Transport documents can be attached later on the Project. "
				"Approve this record, then click <b>Start Shipment</b>."
			)
		elif state and state != "Approved":
			message = _(
				"All requirements met. Approve this record (currently {0}), "
				"then click <b>Start Shipment</b>."
			).format(frappe.utils.escape_html(state))
		else:
			message = _("Approved. Click <b>Start Shipment</b> to create the project.")

	if message:
		parts.append(f'<div class="cgm-shipment-intake-message">{message}</div>')

	return "".join(parts)


@frappe.whitelist()
def get_intake_wizard_context(
	opportunity: str | None = None,
	shipment_type: str | None = None,
) -> dict:
	stage = STAGE_INTAKE
	readiness: dict = {"blockers": [], "primary_transport_document": None}
	if opportunity and frappe.db.exists("Opportunity", opportunity):
		doc = frappe.get_doc("Opportunity", opportunity)
		sync_opportunity_intake_stage(doc)
		stage = doc.get("custom_intake_stage") or STAGE_INTAKE
		readiness = evaluate_start_shipment_readiness(opportunity)
		# Keep stage flags in sync when older saves left intake stuck on step 1.
		stored_stage = frappe.db.get_value("Opportunity", opportunity, "custom_intake_stage")
		if stored_stage != stage:
			updates = {"custom_intake_stage": stage}
			if doc.meta.has_field("custom_primary_doc_linked"):
				updates["custom_primary_doc_linked"] = doc.custom_primary_doc_linked
			if doc.meta.has_field("custom_uses_container_tracking"):
				updates["custom_uses_container_tracking"] = doc.custom_uses_container_tracking
			frappe.db.set_value("Opportunity", opportunity, updates, update_modified=False)
	elif shipment_type:
		# Unsaved / new form: only expose shipment-type flags for preview,
		# never Start Shipment blockers or documents-stage messaging.
		flags = get_shipment_type_flags(shipment_type)
		readiness.update(
			{
				"transport_documents": flags.get("transport_documents") or [],
				"primary_transport_document": flags.get("primary_transport_document"),
				"uses_container_tracking": flags.get("uses_container_tracking"),
				"default_mode_of_transport": flags.get("default_mode_of_transport"),
				"blockers": [],
			}
		)
		stage = STAGE_INTAKE

	return {
		"stage": stage,
		"html": build_intake_wizard_html(stage, readiness),
		"readiness": readiness,
	}
