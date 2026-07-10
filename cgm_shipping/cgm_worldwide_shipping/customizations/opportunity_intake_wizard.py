"""Opportunity Shipment Intake wizard — layout, stages, and CRM field cleanup.

Form disclosure is driven by ``custom_intake_stage`` (``depends_on`` on fields), not
only client-side toggles. Stages:

* intake — Customer + Shipment Type + Client Reference only
* awaiting_primary — saved; user must create/link primary transport document
* documents — primary doc linked; transport info + client documents + containers
* authorization — required documents verified; approve / start shipment
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment import (
	evaluate_start_shipment_readiness,
	get_shipment_type_flags,
	has_any_transport_document,
)

MODULE = "CGM Worldwide Shipping"

STAGE_INTAKE = "intake"
STAGE_AWAITING_PRIMARY = "awaiting_primary"  # Shipment dashboard — add transport documents
STAGE_DOCUMENTS = "documents"
STAGE_AUTHORIZATION = "authorization"

# Always visible on the intake form (new + saved) — never gate with DEP_DOCUMENTS.
INTAKE_ALWAYS_VISIBLE_FIELDS = (
	"company",
	"transaction_date",
	"party_name",
	"custom_shipment_type",
	"custom_client_refrence_no",
)

DEP_DOCUMENTS = (
	"eval:['documents','authorization'].includes(doc.custom_intake_stage) || "
	"doc.custom_primary_doc_linked"
)
DEP_CONTAINER = (
	"eval:(['documents','authorization'].includes(doc.custom_intake_stage) || "
	"doc.custom_primary_doc_linked) && "
	"(doc.custom_uses_container_tracking || doc.custom_bill_of_lading)"
)
DEP_LAYOUT_COLUMNS = (
	"eval:['documents','authorization'].includes(doc.custom_intake_stage) || "
	"doc.custom_primary_doc_linked"
)
READ_ONLY_FROM_PRIMARY = "eval:doc.custom_primary_doc_linked"

# Operational fields revealed only after the primary transport document exists.
DOCUMENTS_STAGE_FIELDS = (
	"custom_mode_of_transport",
	"custom_eta",
	"custom_etd",
	"custom_vessel",
	"custom_airline",
	"custom_handling_agent",
	"custom_shipping_line",
	"custom_shipping_order_ref",
	"custom_booking_ref",
	"custom_delivery_destination",
	"custom_draft_bl_number",
	"custom_clearance_station",
	"custom_station_code",
	"custom_country_of_origin",
	"custom_cargo_type_",
	"custom_batch_no",
	"custom_weight_nw",
	"custom_gross_weight",
	"custom_quantity",
	"custom_description_of_goods",
	"custom_bill_of_lading",
	"custom_air_waybill",
	"custom_booking_confirmation",
	"custom_consignee",
	"custom_section_break_5s7eg",
	"custom_section_break_6qrpr",
	"custom_section_break_jyvyi",
	"custom_column_break_bbq21",
	"custom_clients_documents",
)

CONTAINER_STAGE_FIELDS = (
	"custom_section_break_idqn5",
	"custom_container_information",
)

TRANSPORT_READ_ONLY_FIELDS = (
	"custom_eta",
	"custom_etd",
	"custom_vessel",
	"custom_airline",
	"custom_shipping_line",
	"custom_shipping_order_ref",
	"custom_booking_ref",
	"custom_handling_agent",
	"custom_draft_bl_number",
	"custom_clearance_station",
	"custom_station_code",
	"custom_country_of_origin",
	"custom_cargo_type_",
	"custom_batch_no",
	"custom_quantity",
	"custom_description_of_goods",
	"custom_bill_of_lading",
	"custom_air_waybill",
	"custom_booking_confirmation",
	"custom_mode_of_transport",
)

CRM_FIELDS_TO_HIDE = (
	"customer_name",
	"opportunity_type",
	"opportunity_owner",
	"status",
	"sales_stage",
	"expected_closing",
	"probability",
	"opportunity_amount",
	"base_opportunity_amount",
	"organization_details_section",
	"no_of_employees",
	"annual_revenue",
	"customer_group",
	"industry",
	"state",
	"city",
	"country",
	"territory",
	"market_segment",
	"website",
	"currency",
	"conversion_rate",
	"language",
	"title",
	"first_response_time",
	"lost_detail_section",
	"lost_reasons",
	"order_lost_reason",
	"competitors",
	"contact_info",
	"primary_contact_section",
	"contact_person",
	"job_title",
	"contact_email",
	"contact_mobile",
	"whatsapp",
	"phone",
	"phone_ext",
	"address_contact_section",
	"address_html",
	"customer_address",
	"address_display",
	"contact_html",
	"contact_display",
	"items_section",
	"items",
	"base_total",
	"total",
	"activities_tab",
	"notes_tab",
	"dashboard_tab",
	"more_info",
	"utm_analytics_section",
	"utm_source",
	"utm_medium",
	"utm_campaign",
	"utm_content",
	"section_break_14",
	"column_break_31",
	"column_break_23",
	"column_break_36",
	"column_break_17",
	"column_break1",
	"column_break_54",
	"column_break_22",
	"column_break3",
	"column_break_33",
	"section_break_32",
	"all_activities_section",
	"notes",
	"notes_html",
	"open_activities_html",
	"all_activities_html",
)


def _upsert_cf(dt: str, values: dict) -> None:
	name = f"{dt}-{values['fieldname']}"
	if frappe.db.exists("Custom Field", name):
		doc = frappe.get_doc("Custom Field", name)
		for key, value in values.items():
			setattr(doc, key, value)
		doc.save(ignore_permissions=True)
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	doc.module = MODULE
	for key, value in values.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)


def _set_cf_props(dt: str, fieldname: str, props: dict) -> None:
	"""Update behaviour on an existing Custom Field (skip if missing)."""
	name = f"{dt}-{fieldname}"
	if not frappe.db.exists("Custom Field", name):
		return
	doc = frappe.get_doc("Custom Field", name)
	changed = False
	for key, value in props.items():
		if doc.get(key) != value:
			doc.set(key, value)
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _clear_cf_depends_on(dt: str, fieldname: str) -> None:
	"""Remove depends_on so a field is always visible (empty string hides in Frappe)."""
	name = f"{dt}-{fieldname}"
	if not frappe.db.exists("Custom Field", name):
		return
	if frappe.db.get_value("Custom Field", name, "depends_on"):
		frappe.db.set_value("Custom Field", name, "depends_on", None, update_modified=False)


def _unhide_opportunity_field(fieldname: str) -> None:
	"""Clear hidden property setter so Customize Form and the desk form can show the field."""
	ps_name = f"Opportunity-{fieldname}-hidden"
	if frappe.db.exists("Property Setter", ps_name):
		frappe.db.set_value("Property Setter", ps_name, "value", "0", update_modified=False)


def _configure_opportunity_from_field() -> None:
	"""Keep Opportunity From off the intake UI without breaking Customize Form validation."""
	# Frappe rejects hidden + mandatory unless a default is set.
	_ensure_ps("Opportunity", "opportunity_from", "default", "Customer")
	_ensure_ps("Opportunity", "opportunity_from", "hidden", "1", "Check")


def _configure_naming_series_field() -> None:
	"""Pre-fill Series on new Opportunities; keep the field visible for users."""
	series = "CRM-OPP-.YYYY.-"
	_ensure_ps("Opportunity", "naming_series", "default", series)
	_ensure_ps("Opportunity", "naming_series", "hidden", "0", "Check")


def _ensure_intake_fields_always_visible() -> None:
	for fieldname in INTAKE_ALWAYS_VISIBLE_FIELDS:
		_clear_cf_depends_on("Opportunity", fieldname)
		_unhide_opportunity_field(fieldname)

	_ensure_ps("Opportunity", "transaction_date", "label", "Opportunity Date")
	_ensure_ps("Opportunity", "company", "reqd", "1", "Check")


def _ensure_ps(
	doctype: str,
	field_name: str,
	property_name: str,
	value: str,
	property_type: str = "Data",
) -> None:
	name = f"{doctype}-{field_name}-{property_name}"
	if frappe.db.exists("Property Setter", name):
		frappe.db.set_value("Property Setter", name, "value", value, update_modified=False)
		return
	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": doctype,
			"field_name": field_name,
			"property": property_name,
			"property_type": property_type,
			"value": value,
		}
	).insert(ignore_permissions=True)


def sync_opportunity_intake_stage(doc) -> None:
	"""Set hidden stage flags used by depends_on expressions."""
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
	if mode and doc.meta.has_field("custom_mode_of_transport") and not doc.get("custom_mode_of_transport"):
		doc.custom_mode_of_transport = mode

	primary_linked = has_any_transport_document(doc)
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
	sync_opportunity_intake_stage(doc)


def validate_opportunity_intake(doc, _method=None) -> None:
	if not doc.opportunity_from:
		doc.opportunity_from = "Customer"
	if not doc.party_name:
		frappe.throw(_("Customer is required"), title=_("Shipment Intake"))
	if not (doc.get("custom_shipment_type") or "").strip():
		frappe.throw(_("Shipment Type is required"), title=_("Shipment Intake"))


def sync_opportunity_intake_on_save(doc, _method=None) -> None:
	sync_opportunity_intake_stage(doc)


def ensure_opportunity_intake_wizard_layout() -> None:
	"""Install wizard control fields, depends_on gates, and hide CRM noise."""
	if not frappe.db.exists("DocType", "Opportunity"):
		return

	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_shipment_intake_wizard_html",
			"label": "Shipment Progress",
			"fieldtype": "HTML",
			"insert_after": "workflow_state",
		},
	)
	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_intake_stage",
			"label": "Intake Stage",
			"fieldtype": "Select",
			"options": "\n".join(
				[
					STAGE_INTAKE,
					STAGE_AWAITING_PRIMARY,
					STAGE_DOCUMENTS,
					STAGE_AUTHORIZATION,
				]
			),
			"default": STAGE_INTAKE,
			"hidden": 1,
			"insert_after": "custom_shipment_intake_wizard_html",
		},
	)
	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_primary_doc_linked",
			"label": "Primary Document Linked",
			"fieldtype": "Check",
			"default": "0",
			"hidden": 1,
			"insert_after": "custom_intake_stage",
		},
	)
	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_uses_container_tracking",
			"label": "Uses Container Tracking",
			"fieldtype": "Check",
			"default": "0",
			"hidden": 1,
			"insert_after": "custom_primary_doc_linked",
		},
	)
	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_section_shipment_intake",
			"label": "Shipment Intake",
			"fieldtype": "Section Break",
			"insert_after": "custom_uses_container_tracking",
			"collapsible": 0,
		},
	)
	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_transport_documents_html",
			"label": "Transport Documents",
			"fieldtype": "HTML",
			"insert_after": "custom_client_refrence_no",
			"depends_on": "eval:!doc.__islocal",
		},
	)
	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_section_transport_info",
			"label": "Transport Information",
			"fieldtype": "Section Break",
			"insert_after": "custom_transport_documents_html",
			"hidden": 1,
			"depends_on": "",
			"collapsible": 0,
		},
	)
	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_section_shipment_authorization",
			"label": "Shipment Authorization",
			"fieldtype": "Section Break",
			"insert_after": "custom_clients_documents",
			"depends_on": DEP_DOCUMENTS,
			"collapsible": 0,
		},
	)
	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_intake_readiness_html",
			"label": "Readiness",
			"fieldtype": "HTML",
			"insert_after": "custom_section_shipment_authorization",
			"depends_on": DEP_DOCUMENTS,
		},
	)

	_set_cf_props("Opportunity", "custom_section_transport_document", {"depends_on": DEP_DOCUMENTS})
	_set_cf_props("Opportunity", "custom_section_transport_info", {"hidden": 1, "depends_on": ""})

	for fieldname in DOCUMENTS_STAGE_FIELDS:
		props = {"depends_on": DEP_DOCUMENTS, "hidden": 0}
		if fieldname in TRANSPORT_READ_ONLY_FIELDS:
			props["read_only_depends_on"] = READ_ONLY_FROM_PRIMARY
		_set_cf_props("Opportunity", fieldname, props)

	for fieldname in CONTAINER_STAGE_FIELDS:
		_set_cf_props(
			"Opportunity",
			fieldname,
			{"depends_on": DEP_CONTAINER, "hidden": 0},
		)

	for fieldname in ("column_break0", "column_break_10"):
		_ensure_ps("Opportunity", fieldname, "hidden", "0", "Check")
		_ensure_ps("Opportunity", fieldname, "depends_on", DEP_LAYOUT_COLUMNS)

	# Intake fields — always visible; never use depends_on="" (Frappe treats that as hidden).
	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_shipment_type",
			"label": "Shipment Type",
			"fieldtype": "Link",
			"options": "Shipment Type",
			"insert_after": "party_name",
			"reqd": 1,
			"hidden": 0,
		},
	)
	_upsert_cf(
		"Opportunity",
		{
			"fieldname": "custom_client_refrence_no",
			"label": "Client Reference No",
			"fieldtype": "Data",
			"insert_after": "custom_shipment_type",
			"hidden": 0,
		},
	)
	_clear_cf_depends_on("Opportunity", "custom_shipment_type")
	_clear_cf_depends_on("Opportunity", "custom_client_refrence_no")
	_ensure_intake_fields_always_visible()
	_configure_opportunity_from_field()
	_configure_naming_series_field()

	for fieldname in (
		"custom_consignee",
		"custom_weight_nw",
		"custom_gross_weight",
		"custom_vessel",
		"custom_clearance_station",
		"custom_station_code",
	):
		ps_name = f"Opportunity-{fieldname}-hidden"
		if frappe.db.exists("Property Setter", ps_name):
			frappe.db.set_value("Property Setter", ps_name, "value", "0", update_modified=False)

	_ensure_ps("Opportunity", "party_name", "label", "Customer")
	_ensure_ps("Opportunity", "party_name", "reqd", "1", "Check")

	for fieldname in CRM_FIELDS_TO_HIDE:
		_ensure_ps("Opportunity", fieldname, "hidden", "1", "Check")

	ensure_opportunity_intake_field_order()
	frappe.clear_cache(doctype="Opportunity")


def ensure_opportunity_intake_field_order() -> None:
	"""Put wizard + intake fields first; operational fields follow disclosure stages."""
	ps_name = "Opportunity-main-field_order"
	priority = [
		"workflow_state",
		"custom_shipment_intake_wizard_html",
		"custom_intake_stage",
		"custom_primary_doc_linked",
		"custom_uses_container_tracking",
		"custom_section_shipment_intake",
		"company",
		"transaction_date",
		"party_name",
		"custom_shipment_type",
		"custom_client_refrence_no",
		"custom_transport_documents_html",
		"custom_consignee",
		"custom_mode_of_transport",
		"column_break0",
		"custom_cargo_type_",
		"custom_batch_no",
		"custom_weight_nw",
		"custom_gross_weight",
		"column_break_10",
		"custom_vessel",
		"custom_airline",
		"custom_country_of_origin",
		"custom_clearance_station",
		"custom_station_code",
		"custom_draft_bl_number",
		"custom_eta",
		"custom_etd",
		"custom_shipping_line",
		"custom_delivery_destination",
		"custom_handling_agent",
		"custom_section_break_5s7eg",
		"custom_description_of_goods",
		"custom_section_break_6qrpr",
		"custom_bill_of_lading",
		"custom_air_waybill",
		"custom_booking_confirmation",
		"custom_column_break_bbq21",
		"custom_quantity",
		"custom_section_break_idqn5",
		"custom_container_information",
		"custom_section_break_jyvyi",
		"custom_clients_documents",
		"custom_section_shipment_authorization",
		"custom_intake_readiness_html",
	]
	if not frappe.db.exists("Property Setter", ps_name):
		meta = frappe.get_meta("Opportunity")
		order = [df.fieldname for df in meta.fields]
	else:
		raw = frappe.db.get_value("Property Setter", ps_name, "value") or "[]"
		try:
			order = json.loads(raw)
		except json.JSONDecodeError:
			meta = frappe.get_meta("Opportunity")
			order = [df.fieldname for df in meta.fields]
	if not isinstance(order, list):
		return
	rest = [f for f in order if f not in priority]
	new_order = priority + rest
	if new_order != order:
		if frappe.db.exists("Property Setter", ps_name):
			frappe.db.set_value(
				"Property Setter", ps_name, "value", json.dumps(new_order), update_modified=False
			)
		else:
			frappe.get_doc(
				{
					"doctype": "Property Setter",
					"doctype_or_field": "DocType",
					"doc_type": "Opportunity",
					"property": "field_order",
					"property_type": "Data",
					"value": json.dumps(new_order),
				}
			).insert(ignore_permissions=True)


def _wizard_step_class(current: str, step: str, completed_steps: set[str]) -> str:
	if step == current:
		return "cgm-wizard-step is-active"
	if step in completed_steps:
		return "cgm-wizard-step is-done"
	return "cgm-wizard-step"


def build_intake_wizard_html(stage: str, readiness: dict | None = None) -> str:
	flags = readiness or {}
	completed = set()
	if stage != STAGE_INTAKE:
		completed.add(STAGE_INTAKE)
	if stage in (STAGE_DOCUMENTS, STAGE_AUTHORIZATION):
		completed.add(STAGE_AWAITING_PRIMARY)
	if stage == STAGE_AUTHORIZATION:
		completed.add(STAGE_DOCUMENTS)

	steps = [
		(STAGE_INTAKE, _("1. Shipment Intake"), _("Customer & shipment type")),
		(STAGE_AWAITING_PRIMARY, _("2. Transport Documents"), _("Add documents as they arrive")),
		(STAGE_DOCUMENTS, _("3. Documents"), _("Transport info & verification")),
		(STAGE_AUTHORIZATION, _("4. Start Shipment"), _("Approve & create project")),
	]

	parts = ['<div class="cgm-shipment-intake-wizard">']
	for key, title, subtitle in steps:
		cls = _wizard_step_class(stage, key, completed)
		parts.append(
			f'<div class="{cls}"><div class="cgm-wizard-step-title">{title}</div>'
			f'<div class="cgm-wizard-step-sub">{subtitle}</div></div>'
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
		message = _("All requirements met. Approve this record, then click <b>Start Shipment</b>.")

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
		flags = get_shipment_type_flags(shipment_type)
		readiness.update(flags)
		if stage == STAGE_INTAKE and shipment_type:
			readiness["blockers"] = []

	return {
		"stage": stage,
		"html": build_intake_wizard_html(stage, readiness),
		"readiness": readiness,
	}
