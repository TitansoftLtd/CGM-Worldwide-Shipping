"""Container utilities shared across Bill of Lading, Opportunity, Lead and Project.

Bill of Lading–specific logic (Opportunity sync, submit payload, opportunity
creation) lives on the controller in
``doctype.bill_of_lading.bill_of_lading``.
"""

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import get_bl_config


# ─── Container field helpers ──────────────────────────────────────────────────
def get_container_fields() -> list[str]:
	"""Dynamically fetch relevant fields from Container DocType."""
	skip_types = {
		"Section Break",
		"Column Break",
		"Tab Break",
		"HTML",
		"Button",
		"Heading",
	}
	return [
		field.fieldname
		for field in frappe.get_meta("Container").fields
		if field.fieldtype not in skip_types and not field.hidden
	]

def get_container_type_order() -> list[str]:
	"""Pull container types from Container Type DocType ordered by idx."""
	return frappe.get_all(
		"Container Type",
		fields=["container_type"],
		order_by="idx asc",
		pluck="container_type",
	)

def get_bl_quantity_summary(bl_doc) -> str:
	"""Return container quantity summary for a Bill of Lading document."""
	summary_field = "container_summary"
	if bl_doc.meta.has_field(summary_field) and bl_doc.get(summary_field):
		return bl_doc.get(summary_field)

	from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
		summarize_bl_container_quantities,
	)

	return summarize_bl_container_quantities(bl_doc.name)

# ─── Container row fetching ───────────────────────────────────────────────────
def fetch_container_rows(bill_of_lading: str | None) -> list[dict]:
	if not bill_of_lading or not frappe.db.exists("Bill of Lading", bill_of_lading):
		return []
	return frappe.get_all(
		"Container",
		filters={"parent": bill_of_lading, "parenttype": "Bill of Lading"},
		fields=get_container_fields(),
		order_by="idx asc",
	)

def resolve_bill_of_lading_name(attachment: str) -> str | None:
	"""Resolve a Bill of Lading name from its docname or attachment file path."""
	if not attachment:
		return None
	if frappe.db.exists("Bill of Lading", attachment):
		return attachment

	attachment_field = get_bl_config().get("attachment_field")
	if not attachment_field:
		return None
	return frappe.db.get_value("Bill of Lading", {attachment_field: attachment}, "name")


# ─── Preshipment container sync (Opportunity / Lead / Project) ─────────────────
def sync_preshipment_containers_from_bl(doc, method=None) -> None:
	"""Populate read-only container rows from the linked Bill of Lading before save."""
	config = get_bl_config()
	bl_field = config.get("opportunity_bl_field")
	container_field = config.get("opportunity_container_field")

	if not bl_field or not container_field:
		return
	if not doc.meta.has_field(container_field):
		return

	bl_name = doc.get(bl_field)
	rows = fetch_container_rows(bl_name) if bl_name else []

	doc.set(container_field, [])
	for row in rows:
		doc.append(
			container_field,
			{field: row.get(field) or "" for field in get_container_fields()},
		)

def apply_bill_of_lading_from_source(target_doc, source_doc) -> None:
	"""Copy Bill of Lading link and container rows from source onto target doc."""
	config = get_bl_config()
	bl_field = config.get("opportunity_bl_field")

	if not bl_field or not source_doc or not target_doc.meta.has_field(bl_field):
		return

	bl_name = source_doc.get(bl_field)
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return

	target_doc.set(bl_field, bl_name)
	sync_preshipment_containers_from_bl(target_doc)

	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment_documents import (
		carry_bill_of_lading_attachment_to_project,
	)

	carry_bill_of_lading_attachment_to_project(
		target_doc, bl_name=bl_name, source_doc=source_doc
	)

# ─── Whitelisted API methods ──────────────────────────────────────────────────
@frappe.whitelist()
def get_bl_container_select_options(bill_of_lading: str | None = None) -> list[dict]:
	if not bill_of_lading or not frappe.db.exists("Bill of Lading", bill_of_lading):
		return []
	frappe.has_permission("Bill of Lading", ptype="read", doc=bill_of_lading, throw=True)
	rows = fetch_container_rows(bill_of_lading)

	options = []
	for row in rows:
		number = (row.get("container_number") or "").strip()
		if not number:
			continue
		parts = [number]
		if row.get("type_of_container"):
			parts.append(str(row.type_of_container))
		if row.get("seal_no"):
			parts.append(f"Seal {row.seal_no}")
		options.append({"value": number, "label": " - ".join(parts)})
	return options

@frappe.whitelist()
def get_containers_for_bl_attachment(attachment: str, opportunity: str = None) -> dict:
	"""
	Given a Bill of Lading name or file attachment path, return
	container rows, quantity and attachment in a single response.
	"""
	if not attachment:
		return {"containers": [], "quantity": "", "attachment": ""}

	bl_name = resolve_bill_of_lading_name(attachment)
	if not bl_name:
		frappe.msgprint(
			f"No Bill of Lading found for: {attachment}",
			indicator="orange",
			alert=True,
		)
		return {"containers": [], "quantity": "", "attachment": ""}

	frappe.has_permission("Bill of Lading", ptype="read", doc=bl_name, throw=True)

	bl_doc = frappe.get_doc("Bill of Lading", bl_name)
	attachment_field = get_bl_config().get("attachment_field")

	return {
		"containers": fetch_container_rows(bl_name),
		"quantity": get_bl_quantity_summary(bl_doc),
		"attachment": bl_doc.get(attachment_field) or "" if attachment_field else "",
	}

@frappe.whitelist()
def get_container_rows_for_bill_of_lading(bill_of_lading: str | None = None) -> list[dict]:
	if not bill_of_lading:
		return []
	if not frappe.db.exists("Bill of Lading", bill_of_lading):
		return []
	frappe.has_permission("Bill of Lading", ptype="read", doc=bill_of_lading, throw=True)
	return fetch_container_rows(bill_of_lading)
