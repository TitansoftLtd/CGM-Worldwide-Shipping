import re

import frappe
from frappe.utils import getdate, now_datetime, today
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_reference import (  # noqa: E402,F401
	CGM_REF_PATTERN,
	apply_shipment_data,
	assign_cgm_project_reference,
	build_cgm_ref_no,
	cgm_ref_prefix,
	is_cgm_ref,
	normalize_shipment_classification,
	normalize_shipment_fields_on_doc,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.department import (  # noqa: E402,F401
	DEPARTMENT_NAME_ALIASES,
	get_department_name_stem,
	normalize_department_stem,
	resolve_department_name,
)


from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_documents import (  # noqa: E402,F401
	CUSTOMER_ATTACH_TO_DOCUMENT_CODE,
	OPPORTUNITY_DOCUMENTS_FIELD,
	SHIPMENT_DOCUMENTS_FIELD,
	TASK_DOCUMENTS_FIELD,
	append_task_document_row,
	append_verified_doc_row,
	carry_customer_attachments_to_project,
	carry_preshipment_docs_to_project,
	carry_project_shipment_documents_to_sea_tasks,
	carry_task_documents_to_project,
	document_types_match,
	ensure_document_types,
	ensure_project_shipment_documents_field,
	get_document_type_link_name,
	get_preshipment_attachments,
	get_project_documents_fieldname,
	refresh_project_shipment_documents,
	refresh_projects_for_customer,
	sync_linked_attachments_to_project,
	sync_project_shipment_documents,
)


# ─── Dynamic field discovery ───────────────────────────────────────────────────


def get_field_from_meta(doctype: str, keyword: str) -> str | None:
	"""Find the first fieldname on a DocType that contains keyword."""
	return next(
		(
			field.fieldname
			for field in frappe.get_meta(doctype).fields
			if keyword in field.fieldname
		),
		None,
	)


def get_link_field_for_doctype(doctype: str, target_doctype: str) -> str | None:
	"""Find a Link field on doctype that points to target_doctype."""
	return next(
		(
			field.fieldname
			for field in frappe.get_meta(doctype).fields
			if field.fieldtype == "Link" and field.options == target_doctype
		),
		None,
	)


def get_container_table_field_for_doctype(doctype: str) -> str | None:
	"""Find a child table on doctype whose rows include container_number."""
	return next(
		(
			field.fieldname
			for field in frappe.get_meta(doctype).fields
			if field.fieldtype == "Table"
			and frappe.get_meta(field.options)
			and frappe.get_meta(field.options).has_field("container_number")
		),
		None,
	)


def get_opportunity_documents_field() -> str | None:
	"""Fetch the Clients Documents table fieldname from Opportunity meta."""
	return next(
		(
			field.fieldname
			for field in frappe.get_meta("Opportunity").fields
			if field.fieldtype == "Table"
			and "clients_documents" in field.fieldname
		),
		None,
	)


def get_project_shipment_documents_field() -> str | None:
	"""Fetch the Shipment Documents table fieldname from Project meta."""
	return next(
		(
			field.fieldname
			for field in frappe.get_meta("Project").fields
			if field.fieldtype == "Table"
			and "shipment_documents" in field.fieldname
		),
		None,
	)


@frappe.request_cache
def get_bl_config() -> dict:
	"""Fetch Bill of Lading config from Document Type master - no hardcoding."""
	dt_meta = frappe.get_meta("Document Type")
	config_fields = [
		name
		for name in (
			"linked_doctype",
			"attachment_field",
			"opportunity_bl_field",
			"opportunity_quantity_field",
			"opportunity_container_field",
			"opportunity_source_field",
		)
		if dt_meta.has_field(name)
	]
	config = {}
	if config_fields and dt_meta.has_field("linked_doctype"):
		config = (
			frappe.db.get_value(
				"Document Type",
				{"linked_doctype": "Bill of Lading"},
				config_fields,
				as_dict=True,
			)
			or {}
		)

	if not config.get("attachment_field"):
		config["attachment_field"] = get_field_from_meta("Bill of Lading", "attach_bill")
	if not config.get("opportunity_bl_field"):
		config["opportunity_bl_field"] = get_link_field_for_doctype("Opportunity", "Bill of Lading")
	if not config.get("opportunity_quantity_field"):
		bl_field = config.get("opportunity_bl_field")
		if bl_field:
			config["opportunity_quantity_field"] = get_quantity_field_after("Opportunity", bl_field)
	if not config.get("opportunity_container_field"):
		config["opportunity_container_field"] = get_container_table_field_for_doctype("Opportunity")
	if not config.get("opportunity_source_field"):
		config["opportunity_source_field"] = get_link_field_for_doctype("Bill of Lading", "Opportunity")
	return config


def get_quantity_field_after(doctype: str, anchor_field: str) -> str | None:
	"""First Data/Float/Int field after anchor_field in DocType field order."""
	fields = frappe.get_meta(doctype).fields
	start = next((idx for idx, field in enumerate(fields) if field.fieldname == anchor_field), -1)
	if start < 0:
		return None
	for field in fields[start + 1 :]:
		if field.fieldtype in ("Section Break", "Tab Break"):
			break
		if field.fieldtype == "Table":
			break
		if field.fieldtype in ("Data", "Float", "Int"):
			return field.fieldname
	return None


def get_bl_container_child_field() -> str | None:
	"""Child table on Bill of Lading that holds container rows."""
	return get_container_table_field_for_doctype("Bill of Lading")


def get_awb_value_from_doc(doc) -> str | None:
	"""Return the first non-empty AWB-style field value on a document."""
	for field in doc.meta.fields:
		if field.fieldtype not in ("Data", "Link", "Small Text"):
			continue
		name = field.fieldname.lower()
		if not any(token in name for token in ("awb", "airway", "air_waybill")):
			continue
		value = doc.get(field.fieldname)
		if value not in (None, ""):
			return value
	return None


def get_project_awb_field() -> str | None:
	"""AWB field on Project."""
	return get_field_from_meta("Project", "awb_number") or get_field_from_meta("Project", "awb")


# ─── Moved out of utils.py ────────────────────────────────────────────────────
# Document-type helpers (document_types_match, get_document_type_link_name,
# ensure_document_types) and document-carrying helpers
# (carry_clients_documents_to_project, get_bill_of_lading_attachment_url,
# carry_bill_of_lading_attachment_to_project) now live in shipment_documents.py;
# the doc-type ones are re-exported via the import block above.
#
# Project creation (create_project_from_lead / create_project_from_opportunity
# and their helpers) moved to project.py. The sea-import task plan
# (load_sea_task_template, mark_task_completed, create_sea_import_task_plan*,
# bootstrap_sea_task_plan_for_project, backfill_intake_documents_on_sea_tasks)
# moved to sea_clearance_flow.py.
