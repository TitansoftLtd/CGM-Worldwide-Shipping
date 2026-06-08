"""Bill of Lading ↔ Opportunity sync and container utilities."""

import frappe
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	document_types_match,
	ensure_document_types,
	get_bl_config,
	get_document_type_link_name,
	get_opportunity_documents_field,
)

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


# ─── Opportunity link validation ──────────────────────────────────────────────
def is_valid_opportunity_link(opportunity: str | None) -> bool:
	"""True when opportunity is a saved CRM Opportunity name."""
	if not opportunity:
		return False
	name = str(opportunity).strip()
	if not name or name.startswith("new-"):
		return False
	return bool(frappe.db.exists("Opportunity", name))

def sanitize_bill_of_lading_linked_opportunity(doc) -> None:
	"""Drop unsaved Opportunity ids so Link validation does not block BL save."""
	config = get_bl_config()
	source_field = config.get("opportunity_source_field")
	if not source_field:
		return
	opp = doc.get(source_field)
	if opp and not is_valid_opportunity_link(opp):
		doc.set(source_field, None)

# ─── Opportunity sync ───────────────────────────────────────────────────────────
def resolve_opportunity_for_bl(bl_doc, opportunity: str | None = None) -> str | None:
	"""Return a saved Opportunity name linked to this Bill of Lading."""
	config = get_bl_config()
	source_field = config.get("opportunity_source_field")
	if not source_field:
		return None

	linked = bl_doc.get(source_field)
	if is_valid_opportunity_link(linked):
		return linked

	if is_valid_opportunity_link(opportunity):
		frappe.db.set_value(
			"Bill of Lading",
			bl_doc.name,
			source_field,
			opportunity,
			update_modified=False,
		)
		bl_doc.set(source_field, opportunity)
		return opportunity

	return None

def sync_opportunity_from_submitted_bl(bl_doc, opportunity: str | None = None) -> str | None:
	"""Link submitted BL data back onto the source Opportunity."""
	config = get_bl_config()
	opportunity = resolve_opportunity_for_bl(bl_doc, opportunity)
	if not opportunity:
		return None

	bl_field = config.get("opportunity_bl_field")
	quantity_field = config.get("opportunity_quantity_field")
	attachment_field = config.get("attachment_field")
	clients_field = get_opportunity_documents_field()

	if not bl_field:
		return None

	opp = frappe.get_doc("Opportunity", opportunity)
	changed = False

	if opp.get(bl_field) != bl_doc.name:
		opp.set(bl_field, bl_doc.name)
		changed = True

	attachment_url = bl_doc.get(attachment_field) if attachment_field else None
	if attachment_url and clients_field and opp.meta.has_field(clients_field):
		if prepend_opportunity_bl_document(opp, attachment_url, bl_name=bl_doc.name):
			changed = True

	quantity_summary = get_bl_quantity_summary(bl_doc)
	if quantity_summary and quantity_field and opp.meta.has_field(quantity_field):
		if opp.get(quantity_field) != quantity_summary:
			opp.set(quantity_field, quantity_summary)
			changed = True

	if changed:
		opp.save(ignore_permissions=True)

	return opportunity

def prepend_opportunity_bl_document(opp_doc, attachment_url, bl_name=None) -> bool:
	"""Insert BL row as the first Clients Documents entry on Opportunity."""
	field = get_opportunity_documents_field()
	if not attachment_url or not field or not opp_doc.meta.has_field(field):
		return False

	ensure_document_types()
	document_type = get_document_type_link_name("BL")
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
			"remarks": frappe._("From submitted Bill of Lading {0}").format(bl_name or ""),
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

	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
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
		options.append({"value": number, "label": " — ".join(parts)})
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
	attachment_field = get_bl_config().get("attachment_field")
	linked_opportunity = sync_opportunity_from_submitted_bl(doc, opportunity)

	return {
		"bl_name": doc.name,
		"attachment": doc.get(attachment_field) or "" if attachment_field else "",
		"document_type": get_document_type_link_name("BL"),
		"quantity": get_bl_quantity_summary(doc),
		"opportunity": linked_opportunity,
	}

@frappe.whitelist()
def create_opportunity_from_bill_of_lading(bill_of_lading: str) -> str:
	"""Create a CRM Opportunity from a submitted Bill of Lading.

	The Customer carried on the BL becomes the Opportunity party; the BL link and
	(via the Opportunity ``before_save`` container sync) its container rows flow
	onto the new Opportunity. The BL is back-linked through its opportunity-source
	field so the existing submit-sync keeps both records in step. Re-running this
	returns the already-linked Opportunity instead of creating a duplicate.
	"""
	frappe.has_permission("Opportunity", ptype="create", throw=True)

	if not bill_of_lading or not frappe.db.exists("Bill of Lading", bill_of_lading):
		frappe.throw("Bill of Lading not found", frappe.DoesNotExistError)

	# Prevent copying data out of a source record the user cannot read.
	frappe.has_permission("Bill of Lading", ptype="read", doc=bill_of_lading, throw=True)
	bl = frappe.get_doc("Bill of Lading", bill_of_lading)

	if bl.docstatus != 1:
		frappe.throw("Bill of Lading must be submitted before creating an Opportunity.")

	config = get_bl_config()
	source_field = config.get("opportunity_source_field")
	bl_field = config.get("opportunity_bl_field")

	# Return the existing Opportunity instead of creating a duplicate.
	if source_field:
		existing = bl.get(source_field)
		if is_valid_opportunity_link(existing):
			return existing

	customer = bl.get("customer")
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw("Set a Customer on the Bill of Lading before creating an Opportunity.")

	opp = frappe.new_doc("Opportunity")
	opp.opportunity_from = "Customer"
	opp.party_name = customer

	if bl_field and opp.meta.has_field(bl_field):
		opp.set(bl_field, bl.name)
	# A Bill of Lading is an ocean-freight document, so default the mode to Sea.
	if opp.meta.has_field("custom_mode_of_transport") and not opp.get("custom_mode_of_transport"):
		opp.set("custom_mode_of_transport", "Sea")
	if opp.meta.has_field("custom_consignee"):
		opp.set(
			"custom_consignee",
			frappe.db.get_value("Customer", customer, "customer_name") or customer,
		)

	# before_save (sync_preshipment_containers_from_bl) copies BL container rows.
	opp.insert()

	# Back-link the BL so the on_submit sync keeps both records aligned.
	if source_field and bl.meta.has_field(source_field):
		frappe.db.set_value(
			"Bill of Lading", bl.name, source_field, opp.name, update_modified=False
		)

	return opp.name


# ─── Document event hooks ─────────────────────────────────────────────────────
def bill_of_lading_on_submit(doc, method=None) -> None:
	"""After BL submit: link to Opportunity and prepend BL file in Clients Documents."""
	sync_opportunity_from_submitted_bl(doc)
