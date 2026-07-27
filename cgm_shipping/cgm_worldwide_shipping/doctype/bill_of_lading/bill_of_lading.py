# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Bill of Lading controller and its Opportunity-sync logic.

Container helpers shared with Opportunity/Lead/Project live in
``customizations.shipment``; the Bill of Lading–specific logic lives here,
on the custom doctype it belongs to.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import cint

from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
	ensure_document_types,
	get_document_type_link_name,
	get_opportunity_documents_field,
	prepend_clients_document_row,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch import (
	allocate_fcl_batch_for_doc,
	counts_from_container_rows,
	derived_quantity_from_bl,
	fill_missing_container_row_cargo_sizes,
	format_derived_quantity,
	is_fcl_cargo_type,
	is_lcl_cargo_type,
	normalize_derived_quantity,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
	apply_bl_fields_to_doc,
	bl_propagation_payload,
	get_cargo_type_field,
	normalize_container_row,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import coerce_numeric_fields, get_bl_config

# Planned Booking Confirmation → confirmed Bill of Lading (prefill / link).
BOOKING_TO_BL_FIELDS = (
	("customer", "customer"),
	("client_ref", "client_refrence_no"),
	("shipment_type", "shipment_type"),
	("requested_cargo_type", "cargo_type"),
	("shipping_line", "shipping_line"),
	("vessel", "vessel"),
	("voyage_number", "voyage_number"),
	("port_of_loading", "port_of_loading"),
	("port_of_discharge", "port_of_discharge"),
	("etd", "etd"),
	("eta", "eta"),
	("commodity", "commodity"),
	("gross_weight", "gross_weight"),
	("net_weight", "net_weight"),
	("weight_uom", "weight_uom"),
	("number_of_packages", "number_of_packages"),
	("package_type", "package_type"),
	("batch_no", "batch_no"),
	("linked_opportunity", "linked_opportunity"),
)

# Opportunity scalars used when creating a BL before / without a Booking.
OPPORTUNITY_TO_BL_FIELDS = (
	("party_name", "customer"),
	("custom_client_refrence_no", "client_refrence_no"),
	("custom_shipment_type", "shipment_type"),
	("custom_shipping_line", "shipping_line"),
	("custom_vessel", "vessel"),
	("custom_voyage_number", "voyage_number"),
	("custom_port_of_loading", "port_of_loading"),
	("custom_port_of_discharge", "port_of_discharge"),
	("custom_etd", "etd"),
	("custom_eta", "eta"),
	("custom_description_of_goods", "commodity"),
	("custom_gross_weight", "gross_weight"),
	("custom_net_weight", "net_weight"),
	("custom_weight_uom_", "weight_uom"),
	("custom_number_of_packages", "number_of_packages"),
	("custom_package_type", "package_type"),
	("custom_draft_bl_number", "bl_number"),
)


class BillofLading(Document):
	def autoname(self):
		if not self.bl_number:
			frappe.throw(frappe._("Bill of Lading Number is required"))
		if not self.customer:
			frappe.throw(frappe._("Customer is required"))
		# Quantity / batch stay on their own fields — name is always the BL number.
		ensure_bl_cargo_type(self)
		apply_bl_quantity_and_batch(self)
		resolve_batch_number_for_bl(self)
		self.name = (self.bl_number or "").strip()

	def validate(self):
		coerce_numeric_fields(self, ("gross_weight", "net_weight"), empty_as_zero=True)
		sanitize_bill_of_lading_linked_opportunity(self)
		ensure_bl_cargo_type(self)
		if is_lcl_cargo_type(self.get("cargo_type")):
			if self.meta.has_field("quantity"):
				self.quantity = None
			if self.meta.has_field("batch_no"):
				self.batch_no = None
			return

		sync_bl_quantity_summary(self)
		apply_bl_quantity_and_batch(self)
		sync_bl_quantity_summary(self)

	def before_submit(self):
		ensure_bl_cargo_type(self)

	def on_submit(self):
		"""Link this submitted BL back to its source Opportunity (and Project if any)."""
		opportunity = sync_opportunity_from_submitted_bl(self)
		if opportunity:
			sync_linked_project_from_bl(self, opportunity)
		_sync_seal_records_for_bl(self)

	def on_update(self):
		_sync_seal_records_for_bl(self)

	def on_update_after_submit(self):
		_sync_seal_records_for_bl(self)

	def _summarize_container_quantities(self) -> str:
		"""Return e.g. '6 x 40FT, 7 x 20FT' from this document's container rows."""
		return format_derived_quantity(counts_from_container_rows(self.container_information))


def _sync_seal_records_for_bl(bl) -> None:
	from cgm_shipping.cgm_worldwide_shipping.doctype.seal_record.seal_record import (
		sync_seal_records_from_bill_of_lading,
	)

	sync_seal_records_from_bill_of_lading(bl)


def sync_bl_quantity_summary(doc) -> None:
	"""Keep BL quantity / container_summary aligned with container rows."""
	summary = (doc.get("quantity") or "").strip() or format_derived_quantity(
		counts_from_container_rows(doc.get("container_information"))
	)
	if doc.meta.has_field("container_summary"):
		doc.container_summary = summary
	if doc.meta.has_field("quantity") and summary:
		doc.quantity = summary


def apply_bl_quantity_and_batch(doc) -> None:
	"""Set derived quantity and batch on Bill of Lading (FCL only for batch)."""
	ensure_bl_cargo_type(doc)
	if is_lcl_cargo_type(doc.get("cargo_type")):
		if doc.meta.has_field("quantity"):
			doc.quantity = None
		# LCL must not participate in FCL batch numbering.
		if doc.meta.has_field("batch_no"):
			doc.batch_no = None
		# Drop empty container rows that can appear when toggling from FCL UI.
		_clear_empty_container_rows(doc)
		return

	# Recover cargo_size onto container rows when users filled numbers/seals but
	# left size blank while parent quantity already encodes the size profile.
	parent_qty = (doc.get("quantity") or "").strip()
	if not parent_qty and doc.get("booking_confirmation"):
		parent_qty = (
			frappe.db.get_value("Booking Confirmation", doc.booking_confirmation, "quantity") or ""
		).strip()
	fill_missing_container_row_cargo_sizes(doc.get("container_information"), parent_qty)

	derived = derived_quantity_from_bl(doc) or normalize_derived_quantity(parent_qty)
	if not derived:
		return

	allocate_fcl_batch_for_doc(
		doc,
		cargo_type_field="cargo_type",
		derived_quantity=derived,
	)


def _clear_empty_container_rows(doc) -> None:
	rows = list(doc.get("container_information") or [])
	if not rows:
		return
	kept = []
	for row in rows:
		has_data = any(
			[
				(row.get("container_number") or "").strip(),
				(row.get("cargo_size") or "").strip(),
				(row.get("seal_no") or "").strip(),
			]
		)
		if has_data:
			kept.append(row)
	if len(kept) != len(rows):
		doc.set("container_information", [])
		for row in kept:
			doc.append(
				"container_information",
				{
					"container_number": row.get("container_number"),
					"cargo_size": row.get("cargo_size"),
					"seal_no": row.get("seal_no"),
					"container_tracker": row.get("container_tracker"),
					"demurrage_days": row.get("demurrage_days"),
					"status": row.get("status"),
				},
			)


def build_bill_of_lading_name(
	bl_number: str, quantity: str | None = None, batch_number: int | None = None
) -> str:
	"""Document name is always the Bill of Lading number (FCL and LCL).

	``quantity`` / ``batch_number`` are ignored; kept for call-site compatibility.
	"""
	_ = (quantity, batch_number)
	return (bl_number or "").strip()


def parse_batch_number_from_bl_name(name: str | None) -> int | None:
	"""Extract trailing batch integer from a legacy Bill of Lading name, if present.

	New BLs are named by ``bl_number`` only; batch lives on ``batch_no``.
	"""
	if not name:
		return None
	suffix = str(name).rsplit("-", 1)[-1].strip()
	return int(suffix) if suffix.isdigit() else None


def resolve_batch_number_for_bl(doc) -> int | None:
	"""Batch for a new/amended Bill of Lading.

	FCL: Customer + Shipment Type + Derived Quantity (reuse Booking batch when linked).
	LCL: no batch number.
	"""
	if is_lcl_cargo_type(doc.get("cargo_type")):
		if doc.meta.has_field("batch_no"):
			doc.batch_no = None
		return None

	if doc.get("amended_from") and is_fcl_cargo_type(doc.get("cargo_type")):
		reused = None
		amended = doc.amended_from
		if frappe.db.exists("Bill of Lading", amended):
			raw = frappe.db.get_value("Bill of Lading", amended, "batch_no")
			if raw not in (None, "") and str(raw).strip().isdigit():
				reused = int(str(raw).strip())
		if reused is None:
			reused = parse_batch_number_from_bl_name(amended)
		if reused:
			if doc.meta.has_field("batch_no"):
				doc.batch_no = str(reused)
			return reused

	apply_bl_quantity_and_batch(doc)
	existing = str(doc.get("batch_no") or "").strip()
	if existing.isdigit():
		return int(existing)
	return None


@frappe.whitelist()
def get_customer_batch_numbers(customer: str) -> list[str]:
	"""Distinct batch numbers already used for this customer (Project + B/L)."""
	if not customer:
		return []
	frappe.has_permission("Customer", ptype="read", doc=customer, throw=True)

	batches: set[str] = set()
	if frappe.get_meta("Project").has_field("custom_batch_no"):
		for value in frappe.get_all(
			"Project",
			filters={"customer": customer, "custom_batch_no": ["is", "set"]},
			pluck="custom_batch_no",
		):
			text = str(value or "").strip()
			if text:
				batches.add(text)

	if frappe.get_meta("Bill of Lading").has_field("batch_no"):
		for value in frappe.get_all(
			"Bill of Lading",
			filters={"customer": customer, "batch_no": ["is", "set"]},
			pluck="batch_no",
		):
			text = str(value or "").strip()
			if text:
				batches.add(text)

	if frappe.get_meta("Booking Confirmation").has_field("batch_no"):
		for value in frappe.get_all(
			"Booking Confirmation",
			filters={"customer": customer, "batch_no": ["is", "set"]},
			pluck="batch_no",
		):
			text = str(value or "").strip()
			if text:
				batches.add(text)

	def sort_key(item: str):
		try:
			return (0, int(item))
		except (TypeError, ValueError):
			return (1, item)

	return sorted(batches, key=sort_key)


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


def ensure_bl_cargo_type(doc) -> None:
	"""Keep FCL/LCL classification on the BL when users only fill container/package rows."""
	if (doc.get("cargo_type") or "").strip():
		return

	quantity = (doc.get("quantity") or "").strip()
	if quantity and " x " in quantity.lower():
		doc.cargo_type = "FCL"
		return

	if str(doc.get("batch_no") or "").strip():
		doc.cargo_type = "FCL"
		return

	if any(
		(row.get("container_number") or row.get("cargo_size") or row.get("seal_no"))
		for row in doc.get("container_information") or []
	):
		doc.cargo_type = "FCL"
		return

	if (doc.get("number_of_packages") or "").strip() or (doc.get("package_type") or "").strip():
		doc.cargo_type = "LCL"
		return

	booking = doc.get("booking_confirmation")
	if booking and frappe.db.exists("Booking Confirmation", booking):
		requested = frappe.db.get_value("Booking Confirmation", booking, "requested_cargo_type")
		if requested:
			doc.cargo_type = requested
			return

	for opp_field in ("linked_opportunity", "custom_linked_opportunity"):
		if not doc.meta.has_field(opp_field):
			continue
		opp_name = doc.get(opp_field)
		if not is_valid_opportunity_link(opp_name):
			continue
		opp = frappe.get_doc("Opportunity", opp_name)
		cargo_field = get_cargo_type_field(opp.meta)
		if cargo_field and opp.get(cargo_field):
			doc.cargo_type = opp.get(cargo_field)
			return


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


def expand_requested_cargo_to_container_stubs(rows) -> list[dict]:
	"""Expand FCL requested size×qty rows into one empty Container stub per unit.

	User only fills container_number and seal_no; quantity is derived from the rows.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.fcl_batch import (
		request_row_cargo_size,
		request_row_quantity,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
		resolve_cargo_size_link,
	)

	stubs: list[dict] = []
	for row in rows or []:
		size = request_row_cargo_size(row)
		qty = request_row_quantity(row)
		if not size or qty <= 0:
			continue
		link = resolve_cargo_size_link(size) or size
		for _ in range(qty):
			stubs.append(
				{
					"cargo_size": link,
					"container_number": "",
					"seal_no": "",
				}
			)
	return stubs


def bl_quantity_summary(bl_doc) -> str:
	"""FCL container summary or LCL package summary for Opportunity / Project."""
	summary = format_derived_quantity(counts_from_container_rows(bl_doc.get("container_information")))
	if summary:
		return summary
	pkgs = (bl_doc.get("number_of_packages") or "").strip()
	ptype = (bl_doc.get("package_type") or "").strip()
	if pkgs and ptype:
		return f"{pkgs} {ptype}"
	return pkgs or ptype


def sync_opportunity_from_submitted_bl(bl_doc, opportunity: str | None = None) -> str | None:
	"""Link submitted BL data back onto the source Opportunity (shipment SSoT)."""
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

	# Keep Booking ↔ BL link on Opportunity when the BL was created from a Booking.
	booking = bl_doc.get("booking_confirmation")
	if (
		booking
		and opp.meta.has_field("custom_booking_confirmation")
		and opp.get("custom_booking_confirmation") != booking
	):
		opp.set("custom_booking_confirmation", booking)
		changed = True

	attachment_url = bl_doc.get(attachment_field) if attachment_field else None
	if attachment_url and clients_field and opp.meta.has_field(clients_field):
		if prepend_opportunity_bl_document(opp, attachment_url, bl_name=bl_doc.name):
			changed = True

	quantity_summary = bl_quantity_summary(bl_doc)
	if quantity_summary and quantity_field and opp.meta.has_field(quantity_field):
		if opp.get(quantity_field) != quantity_summary:
			opp.set(quantity_field, quantity_summary)
			changed = True

	if apply_bl_fields_to_doc(opp, bl_doc):
		changed = True

	if changed:
		# Booking-first shipments add their BL after the Opportunity is approved
		# and submitted. This controlled system sync must still carry confirmed
		# BL values back without making those fields manually editable afterward.
		if opp.docstatus == 1:
			opp.flags.ignore_validate_update_after_submit = True
		opp.save(ignore_permissions=True)

	return opportunity


def sync_linked_project_from_bl(bl_doc, opportunity: str) -> str | None:
	"""When a Project already exists, push confirmed BL values from Opportunity/BL.

	Edge case: shipment started from Booking Confirmation, Project created, then BL
	arrives later — Project must replace planned vessel/ETA/etc. with confirmed values.
	"""
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

	config = get_bl_config()
	bl_field = config.get("opportunity_bl_field")
	if bl_field and project.meta.has_field(bl_field) and project.get(bl_field) != bl_doc.name:
		project.set(bl_field, bl_doc.name)
		changed = True

	booking = bl_doc.get("booking_confirmation")
	if (
		booking
		and project.meta.has_field("custom_booking_confirmation")
		and project.get("custom_booking_confirmation") != booking
	):
		project.set("custom_booking_confirmation", booking)
		changed = True

	# Confirmed BL overwrites planned Opportunity-derived values on Project.
	if apply_bl_fields_to_doc(project, bl_doc):
		changed = True

	quantity_field = config.get("opportunity_quantity_field")
	quantity_summary = bl_quantity_summary(bl_doc)
	if quantity_summary and quantity_field and project.meta.has_field(quantity_field):
		if project.get(quantity_field) != quantity_summary:
			project.set(quantity_field, quantity_summary)
			changed = True

	# Align common Opportunity → Project scalars that BL just refreshed on Opportunity.
	for src_field, dest_field in (
		("custom_eta", "custom_eta"),
		("custom_etd", "custom_expected_time_of_depatureetd"),
		("custom_etd", "custom_etd"),
		("custom_voyage_number", "custom_voyage_number"),
		("custom_shipping_line", "custom_shipping_line"),
		("custom_vessel", "custom_vessel"),
		("custom_gross_weight", "custom_gross_weight"),
		("custom_net_weight", "custom_net_weight"),
		("custom_description_of_goods", "custom_description_of_goods"),
		("custom_client_refrence_no", "custom_client_refrence_no"),
		("custom_batch_no", "custom_batch_no"),
		("custom_booking_ref", "custom_booking_ref"),
		("custom_shipping_order_ref", "custom_shipping_order_ref"),
	):
		if not project.meta.has_field(dest_field) or not opp.meta.has_field(src_field):
			continue
		value = opp.get(src_field)
		if value in (None, ""):
			continue
		if project.get(dest_field) != value:
			project.set(dest_field, value)
			changed = True

	from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment import (
		align_project_etd_fields,
	)

	if align_project_etd_fields(project):
		changed = True

	container_field = config.get("opportunity_container_field")
	if container_field and project.meta.has_field(container_field):
		from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import fetch_container_rows

		rows = fetch_container_rows(bl_doc.name)
		project.set(container_field, [])
		for row in rows:
			project.append(container_field, normalize_container_row(row))
		changed = True

	from cgm_shipping.cgm_worldwide_shipping.customizations.documents import (
		sync_project_documents_from_opportunity,
	)

	sync_project_documents_from_opportunity(project, opp)
	project.flags.ignore_validate = True
	project.save(ignore_permissions=True)
	_ = changed

	return project_name


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


def _scalar_seed_value(value):
	if value in (None, ""):
		return None
	return value


def build_bl_seed_from_booking(booking_doc) -> dict:
	"""Prefill payload for a new Bill of Lading created from a Booking Confirmation."""
	seed: dict = {"booking_confirmation": booking_doc.name}
	for src, dest in BOOKING_TO_BL_FIELDS:
		value = _scalar_seed_value(booking_doc.get(src))
		if value is not None:
			seed[dest] = value

	cargo_type = (booking_doc.get("requested_cargo_type") or "").strip()
	if is_fcl_cargo_type(cargo_type):
		stubs = expand_requested_cargo_to_container_stubs(
			booking_doc.get("requested_cargo_quantity")
		)
		seed["container_stubs"] = stubs
		seed["quantity"] = (
			format_derived_quantity(counts_from_container_rows(stubs))
			or booking_doc.get("quantity")
		)
	else:
		seed["container_stubs"] = []

	return seed


def build_bl_seed_from_opportunity(opp) -> dict:
	"""Prefill payload when creating a BL from Opportunity (booking optional)."""
	seed: dict = {}
	if opp.name and is_valid_opportunity_link(opp.name):
		seed["linked_opportunity"] = opp.name

	booking = opp.get("custom_booking_confirmation")
	if booking and frappe.db.exists("Booking Confirmation", booking):
		booking_doc = frappe.get_doc("Booking Confirmation", booking)
		seed.update(build_bl_seed_from_booking(booking_doc))
		# Opportunity link wins if booking missed it.
		if is_valid_opportunity_link(opp.name):
			seed["linked_opportunity"] = opp.name
		return seed

	for src, dest in OPPORTUNITY_TO_BL_FIELDS:
		value = _scalar_seed_value(opp.get(src))
		if value is not None:
			seed[dest] = value

	cargo_field = get_cargo_type_field(opp.meta)
	cargo_type = (opp.get(cargo_field) if cargo_field else None) or ""
	if not cargo_type:
		# Fallback legacy field name on some Opportunity layouts.
		cargo_type = opp.get("custom_cargo_type_") or opp.get("custom_cargo_type") or ""
	if cargo_type:
		seed["cargo_type"] = cargo_type

	if is_fcl_cargo_type(cargo_type) and opp.meta.has_field("custom_requested_cargo_quantity"):
		seed["container_stubs"] = expand_requested_cargo_to_container_stubs(
			opp.get("custom_requested_cargo_quantity")
		)
	else:
		seed["container_stubs"] = []

	return seed


# ─── Whitelisted API ──────────────────────────────────────────────────────────
@frappe.whitelist()
def get_bl_seed_for_opportunity(opportunity: str | None = None) -> dict:
	"""Return BL prefill fields (+ FCL container stubs) from the linked Opportunity/Booking.

	Used by + Add Bill of Lading so users never re-enter planned shipment data.
	"""
	if not is_valid_opportunity_link(opportunity):
		return {}

	frappe.has_permission("Opportunity", ptype="read", doc=opportunity, throw=True)
	opp = frappe.get_doc("Opportunity", opportunity)
	return build_bl_seed_from_opportunity(opp)


@frappe.whitelist()
def get_bl_seed_from_booking(booking_confirmation: str | None = None) -> dict:
	"""Return BL prefill fields from a Booking Confirmation (FCL stubs included)."""
	if not booking_confirmation or not frappe.db.exists("Booking Confirmation", booking_confirmation):
		return {}

	frappe.has_permission(
		"Booking Confirmation", ptype="read", doc=booking_confirmation, throw=True
	)
	booking = frappe.get_doc("Booking Confirmation", booking_confirmation)
	return build_bl_seed_from_booking(booking)


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

	quantity = bl_quantity_summary(doc) or (doc.get("quantity") or "")

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

	# Carry the BL quantity summary onto the Opportunity.
	quantity_field = config.get("opportunity_quantity_field")
	quantity_summary = bl_quantity_summary(bl)
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
