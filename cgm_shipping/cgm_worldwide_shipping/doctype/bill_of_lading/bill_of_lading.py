# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Bill of Lading controller and its Opportunity-sync logic.

Container helpers shared with Opportunity/Lead/Project live in
``customizations.shipment``; the Bill of Lading–specific logic lives here,
on the custom doctype it belongs to.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
	ensure_document_types,
	get_document_type_link_name,
	get_opportunity_documents_field,
	prepend_clients_document_row,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	apply_bl_fields_to_doc,
	bl_propagation_payload,
	container_row_cargo_size,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import get_bl_config, get_link_field_for_doctype


class BillofLading(Document):
	def autoname(self):
		if not self.bl_number:
			frappe.throw(frappe._("Bill of Lading Number is required"))
		if not self.customer:
			frappe.throw(frappe._("Customer is required"))
		quantity = self._quantity_for_naming()
		batch_number = resolve_batch_number_for_bl(self)
		self.name = build_bill_of_lading_name(self.bl_number, quantity, batch_number)

	def _quantity_for_naming(self) -> str:
		"""Quantity segment for the document name (from field or container rows)."""
		if self.get("quantity"):
			return (self.quantity or "").strip()
		return self._summarize_container_quantities()

	def validate(self):
		sanitize_bill_of_lading_linked_opportunity(self)
		batch_number = resolve_batch_number_for_bl(self)
		if not self.get("batch_no"):
			self.batch_no = str(batch_number)
		summary = self._summarize_container_quantities()
		if not summary:
			pkgs = (self.get("number_of_packages") or "").strip()
			ptype = (self.get("package_type") or "").strip()
			if pkgs and ptype:
				summary = f"{pkgs} {ptype}"
			else:
				summary = pkgs or ptype
		if self.meta.has_field("container_summary"):
			self.container_summary = summary
		if self.meta.has_field("quantity"):
			self.quantity = summary

	def on_submit(self):
		"""Link this submitted BL back to its source Opportunity and sync documents."""
		sync_opportunity_from_submitted_bl(self)

	def _summarize_container_quantities(self) -> str:
		"""Return e.g. '6 x 40FT, 7 x 20FT' from this document's container rows."""
		if not self.container_information:
			return ""

		# Fetch order directly from Cargo Size DocType
		display_order = frappe.get_all(
			"Cargo Size",
			fields=["cargo_size"],
			order_by="idx asc",
			pluck="cargo_size",
		)

		counts: dict[str, int] = {}
		for row in self.container_information:
			cargo_size = container_row_cargo_size(row)
			if not cargo_size:
				continue
			counts[cargo_size] = counts.get(cargo_size, 0) + 1

		if not counts:
			return ""

		ordered = [t for t in display_order if t in counts]
		for t in sorted(counts):
			if t not in ordered:
				ordered.append(t)

		return ", ".join(f"{counts[t]} x {t}" for t in ordered)


def build_bill_of_lading_name(
	bl_number: str, quantity: str | None, batch_number: int
) -> str:
	"""BL_NUMBER + ' ' + QUANTITY + '-' + BATCH_NUMBER (e.g. MB-0ONUJ 2 x 20FT-10)."""
	bl_number = (bl_number or "").strip()
	quantity = (quantity or "").strip()
	suffix = f"-{int(batch_number)}"
	if quantity:
		return f"{bl_number} {quantity}{suffix}"
	return f"{bl_number}{suffix}"


def parse_batch_number_from_bl_name(name: str | None) -> int | None:
	"""Extract trailing batch integer from a Bill of Lading name, if present."""
	if not name:
		return None
	suffix = str(name).rsplit("-", 1)[-1].strip()
	return int(suffix) if suffix.isdigit() else None


def lock_customer_for_batch_allocation(customer: str) -> None:
	"""Serialize batch allocation for one customer under concurrent creation."""
	if not customer:
		return
	frappe.db.sql(
		"SELECT name FROM `tabCustomer` WHERE name = %s FOR UPDATE",
		(customer,),
	)


def count_customer_batch_allocations(customer: str) -> int:
	"""Count shipment batches already allocated for a customer (dynamic, no counter table).

	Includes:
	- distinct Projects for the customer that already reference a Bill of Lading
	- Bill of Lading records not yet linked to a Project (draft or submitted)

	Cancelled Bill of Lading records (docstatus = 2) are excluded.
	"""
	if not customer:
		return 0

	project_bl_field = get_link_field_for_doctype("Project", "Bill of Lading")
	if not project_bl_field:
		project_bl_field = "custom_bill_of_lading"

	project_count = frappe.db.sql(
		f"""
		SELECT COUNT(DISTINCT p.name)
		FROM `tabProject` p
		WHERE p.customer = %s
		  AND IFNULL(p.`{project_bl_field}`, '') != ''
		""",
		(customer,),
	)[0][0] or 0

	bol_without_project = frappe.db.sql(
		f"""
		SELECT COUNT(*)
		FROM `tabBill of Lading` bl
		WHERE bl.customer = %s
		  AND bl.docstatus < 2
		  AND NOT EXISTS (
			SELECT 1
			FROM `tabProject` p
			WHERE p.`{project_bl_field}` = bl.name
		  )
		""",
		(customer,),
	)[0][0] or 0

	return int(project_count) + int(bol_without_project)


def next_batch_number_for_customer(customer: str) -> int:
	"""Return the next batch number for a customer (count of existing allocations + 1)."""
	lock_customer_for_batch_allocation(customer)
	return count_customer_batch_allocations(customer) + 1


def resolve_batch_number_for_bl(doc) -> int:
	"""Batch for a new/amended Bill of Lading — prefer linked Opportunity batch."""
	if doc.get("amended_from"):
		reused = parse_batch_number_from_bl_name(doc.amended_from)
		if reused:
			return reused

	config = get_bl_config()
	source_field = config.get("opportunity_source_field") or "linked_opportunity"
	opportunity = doc.get(source_field) or doc.get("custom_linked_opportunity")
	if opportunity and frappe.db.exists("Opportunity", opportunity):
		opp_batch = frappe.db.get_value("Opportunity", opportunity, "custom_batch_no")
		if opp_batch and str(opp_batch).strip().isdigit():
			return int(str(opp_batch).strip())

	return next_batch_number_for_customer(doc.customer)


def summarize_bl_container_quantities(bl_name: str | None) -> str:
	"""Summarize container type counts for a Bill of Lading by name."""
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return ""
	doc = frappe.get_doc("Bill of Lading", bl_name)
	return doc._summarize_container_quantities()


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


# ─── Opportunity sync ─────────────────────────────────────────────────────────
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

	quantity_summary = bl_doc._summarize_container_quantities()
	if not quantity_summary:
		pkgs = (bl_doc.get("number_of_packages") or "").strip()
		ptype = (bl_doc.get("package_type") or "").strip()
		if pkgs and ptype:
			quantity_summary = f"{pkgs} {ptype}"
		else:
			quantity_summary = pkgs or ptype
	if quantity_summary and quantity_field and opp.meta.has_field(quantity_field):
		if opp.get(quantity_field) != quantity_summary:
			opp.set(quantity_field, quantity_summary)
			changed = True

	if apply_bl_fields_to_doc(opp, bl_doc):
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

	return prepend_clients_document_row(
		opp_doc,
		field,
		document_type,
		attachment_url,
		status="Uploaded",
		remarks=frappe._("From submitted Bill of Lading {0}").format(bl_name or ""),
	)


# ─── Whitelisted API ──────────────────────────────────────────────────────────
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

	quantity = doc._summarize_container_quantities() or (doc.get("quantity") or "")
	if not quantity:
		pkgs = (doc.get("number_of_packages") or "").strip()
		ptype = (doc.get("package_type") or "").strip()
		quantity = f"{pkgs} {ptype}".strip() if pkgs or ptype else ""

	return {
		"bl_name": doc.name,
		"attachment": doc.get(attachment_field) or "" if attachment_field else "",
		"document_type": get_document_type_link_name("BL"),
		"quantity": quantity,
		"opportunity": linked_opportunity,
		**bl_propagation_payload(doc),
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

	if source_field:
		existing = bl.get(source_field)
		if is_valid_opportunity_link(existing):
			return existing

	if bl_field:
		existing = frappe.db.get_value("Opportunity", {bl_field: bl.name}, "name")
		if existing:
			if source_field and bl.meta.has_field(source_field):
				frappe.db.set_value(
					"Bill of Lading", bl.name, source_field, existing, update_modified=False
				)
			return existing

	customer = bl.get("customer")
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw("Set a Customer on the Bill of Lading before creating an Opportunity.")

	opp = frappe.new_doc("Opportunity")
	opp.opportunity_from = "Customer"
	opp.party_name = customer

	if bl_field and opp.meta.has_field(bl_field):
		opp.set(bl_field, bl.name)

	apply_bl_fields_to_doc(opp, bl)

	if opp.meta.has_field("custom_consignee"):
		opp.set(
			"custom_consignee",
			frappe.db.get_value("Customer", customer, "customer_name") or customer,
		)

	# Shipment type, mode, and tracking fields are copied from the BL via apply_bl_fields_to_doc.
	if opp.meta.has_field("custom_description_of_goods") and bl.get("description"):
		opp.set("custom_description_of_goods", bl.get("description"))

	# Carry the BL quantity summary onto the Opportunity.
	quantity_field = config.get("opportunity_quantity_field")
	quantity_summary = bl._summarize_container_quantities()
	if quantity_summary and quantity_field and opp.meta.has_field(quantity_field):
		opp.set(quantity_field, quantity_summary)

	# Add the BL attachment as the first row of the Opportunity documents table.
	attachment_field = config.get("attachment_field")
	attachment_url = bl.get(attachment_field) if attachment_field else None
	clients_field = get_opportunity_documents_field()
	if attachment_url and clients_field and opp.meta.has_field(clients_field):
		prepend_opportunity_bl_document(opp, attachment_url, bl_name=bl.name)

	# before_save (sync_preshipment_containers_from_bl) copies BL container rows.
	opp.insert()

	# Back-link the BL so the on_submit sync keeps both records aligned.
	if source_field and bl.meta.has_field(source_field):
		frappe.db.set_value(
			"Bill of Lading", bl.name, source_field, opp.name, update_modified=False
		)

	return opp.name
