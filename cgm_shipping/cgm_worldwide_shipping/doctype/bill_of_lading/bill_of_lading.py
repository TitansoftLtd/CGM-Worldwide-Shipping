# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt
"""Bill of Lading controller and its Opportunity-sync logic.

Container helpers shared with Opportunity/Lead/Project live in
``customizations.shipment``; the Bill of Lading–specific logic lives here,
on the custom doctype it belongs to.
"""

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, today

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	DEPOSIT_ARRANGEMENT_CONTAINER,
	DEPOSIT_ARRANGEMENT_REVOLVING,
	DEPOSIT_PAYERS,
	DEPOSIT_PAYMENT_STATUSES,
	DEPOSIT_REFUND_STATUSES,
)
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
from cgm_shipping.cgm_worldwide_shipping.customizations.utils import (
	coerce_numeric_fields,
	get_bl_config,
	get_cgm_shipping_settings,
)

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
)


class BillofLading(Document):
	def autoname(self):
		if not self.bl_number:
			frappe.throw(frappe._("Bill of Lading Number is required"))
		if not self.customer:
			frappe.throw(frappe._("Customer is required"))
		ensure_bl_cargo_type(self)
		apply_bl_quantity_and_batch(self)
		resolve_batch_number_for_bl(self)
		bl_number = (self.bl_number or "").strip()
		if self.amended_from:
			# Cancelled originals keep the business number as their document name.
			self.name = amended_bill_of_lading_name(bl_number, self.amended_from)
		else:
			self.name = bl_number

	def validate(self):
		coerce_numeric_fields(self, ("gross_weight", "net_weight"), empty_as_zero=True)
		sanitize_bill_of_lading_linked_opportunity(self)
		validate_unique_active_bl_number(self)
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
		_refresh_bl_container_deposit(self)

	def before_submit(self):
		ensure_bl_cargo_type(self)
		validate_unique_active_bl_number(self)

	def before_cancel(self):
		release_preshipment_bl_links(self.name)

	def on_submit(self):
		"""Link this submitted BL back to its source Opportunity (and Project if any)."""
		opportunity = sync_opportunity_from_submitted_bl(self)
		if opportunity:
			sync_linked_project_from_bl(self, opportunity)
		_sync_seal_records_for_bl(self)

	def on_update(self):
		_sync_seal_records_for_bl(self)
		_sync_bl_deposit_to_tasks(self)

	def on_update_after_submit(self):
		_sync_seal_records_for_bl(self)
		_sync_bl_deposit_to_tasks(self)

	def _summarize_container_quantities(self) -> str:
		"""Return e.g. '6 x 40FT, 7 x 20FT' from this document's container rows."""
		return format_derived_quantity(counts_from_container_rows(self.container_information))


def _sync_seal_records_for_bl(bl) -> None:
	from cgm_shipping.cgm_worldwide_shipping.doctype.seal_record.seal_record import (
		sync_seal_records_from_bill_of_lading,
	)

	sync_seal_records_from_bill_of_lading(bl)


def _refresh_bl_container_deposit(bl) -> None:
	if not bl.meta.has_field("deposit_arrangement"):
		return
	refresh_bl_deposit_payment_status(bl)
	maybe_start_bl_deposit_refund_tracking(bl)


def _sync_bl_deposit_to_tasks(bl) -> None:
	"""Push BL deposit confirmation onto Shipping Line Application tasks (read-only mirror)."""
	if frappe.flags.get("cgm_syncing_bl_deposit_to_task"):
		return
	sync_bl_deposit_to_shipping_line_tasks(bl)


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
	"""Document name is the Bill of Lading number for first-version BLs.

	Amended BLs use ``amended_bill_of_lading_name`` instead. ``quantity`` /
	``batch_number`` are ignored; kept for call-site compatibility.
	"""
	_ = (quantity, batch_number)
	return (bl_number or "").strip()


def amended_bill_of_lading_name(bl_number: str, amended_from: str) -> str:
	"""Unique document name for an amended Bill of Lading (``{bl_number}-1``, …)."""
	bl_number = (bl_number or "").strip()
	if not bl_number or not amended_from:
		return bl_number

	version = 0
	current = amended_from
	while current:
		version += 1
		current = frappe.db.get_value("Bill of Lading", current, "amended_from")

	candidate = f"{bl_number}-{version}"
	while frappe.db.exists("Bill of Lading", candidate):
		version += 1
		candidate = f"{bl_number}-{version}"
	return candidate


def validate_unique_active_bl_number(doc) -> None:
	"""Only one submitted Bill of Lading may use a given B/L number."""
	bl_number = (doc.get("bl_number") or "").strip()
	if not bl_number:
		return

	duplicate = frappe.db.get_value(
		"Bill of Lading",
		{
			"bl_number": bl_number,
			"docstatus": 1,
			"name": ["!=", doc.name or ""],
		},
		"name",
	)
	if duplicate:
		frappe.throw(
			frappe._(
				"Bill of Lading Number {0} is already used by submitted record {1}"
			).format(bl_number, duplicate)
		)


def release_preshipment_bl_links(bl_name: str) -> None:
	"""Clear Opportunity/Project/Lead links that block cancel/amend of a Bill of Lading."""
	if not bl_name:
		return

	bl_field = get_bl_config().get("opportunity_bl_field") or "custom_bill_of_lading"
	for doctype in ("Opportunity", "Project", "Lead"):
		if not frappe.get_meta(doctype).has_field(bl_field):
			continue
		for docname in frappe.get_all(doctype, filters={bl_field: bl_name}, pluck="name"):
			frappe.db.set_value(doctype, docname, bl_field, None, update_modified=False)


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


# ---------------------------------------------------------------------------
# Container deposits (BL-level hold/refund via Journal Entry)
# ---------------------------------------------------------------------------

DEPOSIT_JE_KIND_OUTBOUND = "Outbound"
DEPOSIT_JE_KIND_REFUND = "Refund"


def _bl_meta():
	return frappe.get_meta("Bill of Lading")


def _je_meta():
	return frappe.get_meta("Journal Entry")


def is_deposit_journal_entry(je) -> bool:
	if not je:
		return False
	kind = (je.get("custom_cgm_deposit_entry_kind") or "").strip()
	if kind in (DEPOSIT_JE_KIND_OUTBOUND, DEPOSIT_JE_KIND_REFUND):
		return True
	if je.meta.has_field("custom_cgm_source_bill_of_lading") and je.get(
		"custom_cgm_source_bill_of_lading"
	):
		return True
	# Legacy per-tracker deposit JEs
	if je.meta.has_field("custom_cgm_source_container_tracker"):
		return bool(je.get("custom_cgm_source_container_tracker"))
	return False


def get_container_deposit_account(company: str | None = None) -> str | None:
	settings = get_cgm_shipping_settings()
	if not settings or not settings.meta.has_field("container_deposit_account"):
		return None
	account = (settings.get("container_deposit_account") or "").strip()
	if not account:
		return None
	if company:
		acc_company = frappe.db.get_value("Account", account, "company")
		if acc_company and acc_company != company:
			return None
	return account


def get_bill_of_lading_for_project(project: str | None) -> str | None:
	if not project:
		return None
	bl = frappe.db.get_value("Project", project, "custom_bill_of_lading")
	if bl and frappe.db.exists("Bill of Lading", bl):
		return bl
	return None


def bl_deposit_arrangement(bl) -> str:
	return (bl.get("deposit_arrangement") or "").strip()


def is_container_deposit_bl(bl) -> bool:
	return bl_deposit_arrangement(bl) == DEPOSIT_ARRANGEMENT_CONTAINER


def is_revolving_fund_bl(bl) -> bool:
	return bl_deposit_arrangement(bl) == DEPOSIT_ARRANGEMENT_REVOLVING


def bl_deposit_payer(bl) -> str:
	return (bl.get("deposit_payer") or "").strip()


def bl_is_refundable(bl) -> bool:
	"""Refundable when Customer or Company paid — not Agent."""
	if not is_container_deposit_bl(bl):
		return False
	return bl_deposit_payer(bl) in ("Customer", "Company")


def rollup_bl_deposit_amount(bl) -> float:
	"""Sum per-container deposit amounts when BL arrangement is Container Deposit."""
	if not is_container_deposit_bl(bl):
		return 0.0
	total = 0.0
	for row in bl.get("container_information") or []:
		total += flt(row.get("deposit_amount"))
	return total


def refresh_bl_deposit_payment_status(bl) -> None:
	"""Derive BL deposit_payment_status and roll up deposit_amount."""
	if not bl.meta.has_field("deposit_payment_status"):
		return

	if bl.meta.has_field("deposit_amount"):
		bl.deposit_amount = rollup_bl_deposit_amount(bl)

	if not is_container_deposit_bl(bl):
		bl.deposit_payment_status = DEPOSIT_PAYMENT_STATUSES[0]  # Not Applicable
		return

	je_name = (
		bl.get("deposit_payment_journal_entry")
		if bl.meta.has_field("deposit_payment_journal_entry")
		else None
	)
	if je_name and frappe.db.get_value("Journal Entry", je_name, "docstatus") == 1:
		bl.deposit_payment_status = DEPOSIT_PAYMENT_STATUSES[2]  # Paid
	else:
		bl.deposit_payment_status = DEPOSIT_PAYMENT_STATUSES[1]  # Unpaid


def _tracker_return_date(ct) -> str | None:
	actual = ct.get("actual_empty_return")
	interchange = ct.get("interchange_date")
	if actual and interchange:
		return max(getdate(actual), getdate(interchange)).isoformat()
	if actual or interchange:
		return getdate(actual or interchange).isoformat()
	return None


def get_trackers_for_bl(bl_name: str) -> list[dict]:
	"""Container Trackers linked to this BL (via tracker link on child rows or project/bl_number)."""
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return []

	tracker_names = set()
	for row in frappe.get_all(
		"Container",
		filters={"parent": bl_name, "parenttype": "Bill of Lading"},
		fields=["container_tracker", "container_number"],
	):
		if row.container_tracker:
			tracker_names.add(row.container_tracker)

	projects = frappe.get_all(
		"Project", filters={"custom_bill_of_lading": bl_name}, pluck="name"
	)
	filters = []
	if tracker_names:
		filters.append(["name", "in", list(tracker_names)])
	if projects:
		filters.append(["project", "in", projects])
	# Also match by bl_number data field
	filters.append(["bl_number", "=", bl_name])

	seen = set()
	rows = []
	fields = [
		"name",
		"container_number",
		"project",
		"status",
		"actual_empty_return",
		"interchange_date",
	]
	for f in filters:
		for ct in frappe.get_all("Container Tracker", filters=[f], fields=fields):
			if ct.name in seen:
				continue
			seen.add(ct.name)
			rows.append(ct)
	return rows


def bl_all_containers_returned(bl_name: str) -> tuple[bool, str | None]:
	"""True when every linked tracker has empty return or interchange.

	Returns (all_returned, latest_return_date).
	"""
	trackers = get_trackers_for_bl(bl_name)
	if not trackers:
		# Fall back to BL child rows that have no trackers yet — not ready
		child_count = frappe.db.count(
			"Container", {"parent": bl_name, "parenttype": "Bill of Lading"}
		)
		if child_count:
			return False, None
		return False, None

	dates = []
	for ct in trackers:
		rd = _tracker_return_date(ct)
		if not rd:
			return False, None
		dates.append(getdate(rd))
	return True, max(dates).isoformat()


def maybe_start_bl_deposit_refund_tracking(bl) -> None:
	"""When refundable BL deposit is paid and all containers returned, start refund tracking."""
	if not bl_is_refundable(bl):
		return
	if bl.get("deposit_payment_status") != DEPOSIT_PAYMENT_STATUSES[2]:
		return

	all_returned, return_date = bl_all_containers_returned(bl.name)
	if not all_returned or not return_date:
		return

	status = (bl.get("deposit_refund_status") or "").strip()
	if status in (DEPOSIT_REFUND_STATUSES[2], DEPOSIT_REFUND_STATUSES[3]):  # Received, Forfeited
		return
	if not status:
		bl.deposit_refund_status = DEPOSIT_REFUND_STATUSES[0]  # Pending

	if bl.meta.has_field("deposit_return_date") and not bl.get("deposit_return_date"):
		bl.deposit_return_date = return_date


def sync_bl_deposit_from_tracker_update(ct, method=None) -> None:
	"""Hook from Container Tracker validate: maybe start BL refund when returns complete."""
	bl_name = (ct.get("bl_number") or "").strip()
	if not bl_name and ct.get("project"):
		bl_name = get_bill_of_lading_for_project(ct.project) or ""
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return
	bl = frappe.get_doc("Bill of Lading", bl_name)
	if not is_container_deposit_bl(bl):
		return

	before = {
		"deposit_refund_status": bl.get("deposit_refund_status"),
		"deposit_return_date": bl.get("deposit_return_date"),
	}
	refresh_bl_deposit_payment_status(bl)
	maybe_start_bl_deposit_refund_tracking(bl)
	updates = {}
	if bl.get("deposit_refund_status") != before["deposit_refund_status"]:
		updates["deposit_refund_status"] = bl.deposit_refund_status or ""
	if bl.meta.has_field("deposit_return_date") and bl.get("deposit_return_date") != before[
		"deposit_return_date"
	]:
		updates["deposit_return_date"] = bl.deposit_return_date
	if bl.meta.has_field("deposit_payment_status"):
		updates["deposit_payment_status"] = bl.deposit_payment_status
	if bl.meta.has_field("deposit_amount"):
		updates["deposit_amount"] = bl.deposit_amount
	if updates:
		frappe.db.set_value("Bill of Lading", bl_name, updates, update_modified=False)
		if "deposit_refund_status" in updates:
			project = _project_for_bl(bl_name)
			if project:
				_sync_project_deposit_refund_mirror(project, bl_name)


def sync_bl_deposit_to_shipping_line_tasks(bl) -> None:
	"""Mirror BL deposit arrangement + per-container amounts onto Shipping Line tasks."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		TASK_CONTAINER_UPDATES_FIELD,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		shipping_line_application_sequences,
		shipping_line_finance_payment_sequences,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
		task_flow_key_in_filter,
	)

	if not bl or not bl.name:
		return
	projects = frappe.get_all(
		"Project", filters={"custom_bill_of_lading": bl.name}, pluck="name"
	)
	if not projects:
		return

	seqs = sorted(
		set(shipping_line_application_sequences()) | set(shipping_line_finance_payment_sequences())
	)
	if not seqs:
		return

	arrangement = bl_deposit_arrangement(bl)
	by_number = {
		(r.get("container_number") or "").strip().upper(): r
		for r in (bl.get("container_information") or [])
		if (r.get("container_number") or "").strip()
	}

	frappe.flags.cgm_syncing_bl_deposit_to_task = True
	try:
		for project in projects:
			tasks = frappe.get_all(
				"Task",
				filters={
					"project": project,
					"custom_task_flow_key": task_flow_key_in_filter(),
					"custom_sequence_no": ["in", seqs],
					"status": ["!=", "Cancelled"],
				},
				pluck="name",
			)
			for task_name in tasks:
				task = frappe.get_doc("Task", task_name)
				changed = False
				if task.meta.has_field("custom_bl_deposit_arrangement"):
					if (task.get("custom_bl_deposit_arrangement") or "") != arrangement:
						task.custom_bl_deposit_arrangement = arrangement
						changed = True
				if task.meta.has_field("custom_bl_has_deposit"):
					has_deposit = 1 if is_container_deposit_bl(bl) else 0
					if cint(task.get("custom_bl_has_deposit")) != has_deposit:
						task.custom_bl_has_deposit = has_deposit
						changed = True
				if task.meta.has_field("custom_deposit_payer") and bl_deposit_payer(bl):
					if (task.get("custom_deposit_payer") or "") != bl_deposit_payer(bl):
						task.custom_deposit_payer = bl_deposit_payer(bl)
						changed = True
				if task.meta.has_field(TASK_CONTAINER_UPDATES_FIELD) and is_container_deposit_bl(bl):
					for row in task.get(TASK_CONTAINER_UPDATES_FIELD) or []:
						key = (row.get("container_number") or "").strip().upper()
						src = by_number.get(key)
						if not src:
							continue
						new_amt = flt(src.get("deposit_amount"))
						if flt(row.get("deposit_amount")) != new_amt:
							row.deposit_amount = new_amt
							changed = True
				if changed:
					task.flags.ignore_permissions = True
					task.save()
	finally:
		frappe.flags.cgm_syncing_bl_deposit_to_task = False


def sync_project_deposit_payment_statuses(project: str | None) -> int:
	"""Refresh deposit status on the project's Bill of Lading."""
	bl_name = get_bill_of_lading_for_project(project)
	if not bl_name:
		return 0
	bl = frappe.get_doc("Bill of Lading", bl_name)
	before = bl.get("deposit_payment_status")
	refresh_bl_deposit_payment_status(bl)
	maybe_start_bl_deposit_refund_tracking(bl)
	updates = {}
	if bl.get("deposit_payment_status") != before:
		updates["deposit_payment_status"] = bl.deposit_payment_status
	if bl.meta.has_field("deposit_amount"):
		updates["deposit_amount"] = bl.deposit_amount
	if bl.meta.has_field("deposit_refund_status"):
		updates["deposit_refund_status"] = bl.get("deposit_refund_status") or ""
	if bl.meta.has_field("deposit_return_date"):
		updates["deposit_return_date"] = bl.get("deposit_return_date")
	if updates:
		frappe.db.set_value("Bill of Lading", bl_name, updates, update_modified=False)
		return 1
	return 0


def get_deposit_bl_for_project(project: str) -> dict | None:
	"""Return BL deposit summary for a project when arrangement is Container Deposit."""
	bl_name = get_bill_of_lading_for_project(project)
	if not bl_name:
		return None
	fields = [
		"name",
		"bl_number",
		"deposit_arrangement",
		"deposit_currency",
		"deposit_payer",
		"deposit_amount",
		"deposit_payment_status",
		"deposit_payment_journal_entry",
		"deposit_refund_status",
		"deposit_refund_journal_entry",
		"deposit_return_date",
		"deposit_sales_invoice",
		"deposit_credit_note",
		"deposit_company_invoice_pending",
	]
	meta = _bl_meta()
	fields = [f for f in fields if meta.has_field(f) or f in ("name", "bl_number")]
	row = frappe.db.get_value("Bill of Lading", bl_name, fields, as_dict=True)
	if not row or bl_deposit_arrangement(row) != DEPOSIT_ARRANGEMENT_CONTAINER:
		return None
	row["is_refundable"] = bl_is_refundable(row)
	row["containers"] = frappe.get_all(
		"Container",
		filters={"parent": bl_name, "parenttype": "Bill of Lading"},
		fields=["name", "container_number", "deposit_amount", "container_tracker"],
		order_by="idx asc",
	)
	return row


@frappe.whitelist()
def get_project_company_deposit_invoice_context(project: str) -> dict | None:
	"""Return Company-path deposit billing state for project toolbar actions."""
	if not project or not frappe.db.exists("Project", project):
		return None
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	bl = get_deposit_bl_for_project(project)
	if not bl or bl_deposit_payer(bl) != "Company":
		return None
	return {
		"bill_of_lading": bl.get("name"),
		"bl_number": bl.get("bl_number"),
		"deposit_amount": flt(bl.get("deposit_amount")),
		"deposit_sales_invoice": bl.get("deposit_sales_invoice"),
		"deposit_company_invoice_pending": cint(bl.get("deposit_company_invoice_pending")),
	}


def _user_can_manage_deposit_refund() -> bool:
	return bool(
		{"Finance Manager", "Finance User", "Accounts User", "Accounts Manager", "System Manager"}
		& set(frappe.get_roles())
	)


def _project_for_bl(bill_of_lading: str) -> str | None:
	return frappe.db.get_value("Project", {"custom_bill_of_lading": bill_of_lading}, "name")


def _sync_project_deposit_refund_mirror(
	project: str, bl_name: str, confirmed_by: str | None = None
) -> None:
	"""Mirror BL deposit refund status onto the Project (read-only display fields)."""
	if not project or not bl_name:
		return
	meta = frappe.get_meta("Project")
	if not meta.has_field("custom_container_deposit_refund_status"):
		return

	bl = frappe.db.get_value(
		"Bill of Lading",
		bl_name,
		["deposit_refund_status", "deposit_refund_applied_on"],
		as_dict=True,
	)
	if not bl:
		return

	refund = (bl.get("deposit_refund_status") or "").strip()
	confirmed = refund == DEPOSIT_REFUND_STATUSES[2]
	updates = {
		"custom_container_deposit_refund_status": refund,
		"custom_container_deposit_refund_confirmed": 1 if confirmed else 0,
	}
	if meta.has_field("custom_container_deposit_refund_confirmed_on"):
		updates["custom_container_deposit_refund_confirmed_on"] = (
			bl.get("deposit_refund_applied_on") if confirmed else None
		)
	if meta.has_field("custom_container_deposit_refund_confirmed_by"):
		if confirmed:
			updates["custom_container_deposit_refund_confirmed_by"] = (
				confirmed_by
				or frappe.db.get_value(
					"Project", project, "custom_container_deposit_refund_confirmed_by"
				)
				or frappe.session.user
			)
		else:
			updates["custom_container_deposit_refund_confirmed_by"] = None

	frappe.db.set_value("Project", project, updates, update_modified=False)


def _validate_project_deposit_refund_confirmation(project: str, bl: dict) -> None:
	if not bl or bl_deposit_arrangement(bl) != DEPOSIT_ARRANGEMENT_CONTAINER:
		frappe.throw(_("This project has no container deposit on the linked Bill of Lading."))
	if not bl_is_refundable(bl):
		frappe.throw(_("This container deposit is not refundable (Agent-paid deposits are not tracked)."))
	if (bl.get("deposit_payment_status") or "") != DEPOSIT_PAYMENT_STATUSES[2]:
		frappe.throw(_("The container deposit must be paid before confirming a refund."))
	if (bl.get("deposit_refund_status") or "") != DEPOSIT_REFUND_STATUSES[0]:
		frappe.throw(
			_("Deposit refund is not pending - current status is <b>{0}</b>.").format(
				bl.get("deposit_refund_status") or _("Not started")
			)
		)


@frappe.whitelist()
def get_project_deposit_refund_context(project: str) -> dict | None:
	"""Return container deposit refund state for Project toolbar actions and form mirror."""
	if not project or not frappe.db.exists("Project", project):
		return None
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	bl = get_deposit_bl_for_project(project)
	if not bl or bl_deposit_arrangement(bl) != DEPOSIT_ARRANGEMENT_CONTAINER:
		return None

	refund = (bl.get("deposit_refund_status") or "").strip()
	payment = (bl.get("deposit_payment_status") or "").strip()
	refundable = bl_is_refundable(bl)
	has_refund_je = bool(bl.get("deposit_refund_journal_entry"))
	refund_je_docstatus = (
		frappe.db.get_value("Journal Entry", bl.deposit_refund_journal_entry, "docstatus")
		if has_refund_je
		else None
	)

	can_manage = _user_can_manage_deposit_refund()
	can_confirm = (
		can_manage
		and refundable
		and payment == DEPOSIT_PAYMENT_STATUSES[2]
		and refund == DEPOSIT_REFUND_STATUSES[0]
	)
	can_record_je = (
		can_manage
		and refundable
		and payment == DEPOSIT_PAYMENT_STATUSES[2]
		and refund == DEPOSIT_REFUND_STATUSES[0]
		and (not has_refund_je or refund_je_docstatus == 2)
		and frappe.has_permission("Journal Entry", ptype="create")
	)
	can_forfeit = (
		can_manage
		and refundable
		and payment == DEPOSIT_PAYMENT_STATUSES[2]
		and refund == DEPOSIT_REFUND_STATUSES[0]
		and "Accounts Manager" in frappe.get_roles()
	)
	can_credit_note = (
		can_manage
		and refundable
		and payment == DEPOSIT_PAYMENT_STATUSES[2]
		and bl_deposit_payer(bl) == "Customer"
		and bl.get("deposit_sales_invoice")
		and not bl.get("deposit_credit_note")
		and frappe.has_permission("Sales Invoice", ptype="create")
	)

	project_confirmed = cint(
		frappe.db.get_value("Project", project, "custom_container_deposit_refund_confirmed")
	)

	return {
		"bill_of_lading": bl.get("name"),
		"bl_number": bl.get("bl_number"),
		"deposit_amount": flt(bl.get("deposit_amount")),
		"deposit_payment_status": payment,
		"deposit_refund_status": refund,
		"deposit_return_date": bl.get("deposit_return_date"),
		"deposit_refund_journal_entry": bl.get("deposit_refund_journal_entry"),
		"deposit_credit_note": bl.get("deposit_credit_note"),
		"deposit_refund_confirmed": project_confirmed or refund == DEPOSIT_REFUND_STATUSES[2],
		"can_confirm_refund": can_confirm,
		"can_record_refund_je": can_record_je,
		"can_mark_forfeited": can_forfeit,
		"can_create_credit_note": can_credit_note,
	}


@frappe.whitelist()
def confirm_container_deposit_refund_for_project(project: str) -> dict:
	"""Finance confirms on Project that the shipping line returned the container deposit."""
	if not project or not frappe.db.exists("Project", project):
		frappe.throw(_("Project not found."))
	frappe.has_permission("Project", ptype="write", doc=project, throw=True)
	if not _user_can_manage_deposit_refund():
		frappe.throw(_("You do not have permission to confirm container deposit refunds."))

	bl = get_deposit_bl_for_project(project)
	if not bl:
		frappe.throw(_("No Bill of Lading with a container deposit on this project."))
	_validate_project_deposit_refund_confirmation(project, bl)

	bl_name = bl["name"]
	_mark_refund_received(bl_name)
	_sync_project_deposit_refund_mirror(project, bl_name, confirmed_by=frappe.session.user)
	meta = frappe.get_meta("Project")
	if meta.has_field("custom_container_deposit_refund_confirmed_on"):
		frappe.db.set_value(
			"Project",
			project,
			"custom_container_deposit_refund_confirmed_on",
			now_datetime(),
			update_modified=False,
		)
	return get_project_deposit_refund_context(project) or {}


@frappe.whitelist()
def mark_container_deposit_refund_forfeited_for_project(project: str) -> dict:
	"""Mark a pending container deposit refund as forfeited (from Project)."""
	if not project or not frappe.db.exists("Project", project):
		frappe.throw(_("Project not found."))
	frappe.has_permission("Project", ptype="write", doc=project, throw=True)
	if "Accounts Manager" not in frappe.get_roles():
		frappe.throw(_("Only Accounts Manager can mark a deposit as forfeited."))

	bl = get_deposit_bl_for_project(project)
	if not bl:
		frappe.throw(_("No Bill of Lading with a container deposit on this project."))
	_validate_project_deposit_refund_confirmation(project, bl)

	bl_name = bl["name"]
	frappe.db.set_value(
		"Bill of Lading",
		bl_name,
		{"deposit_refund_status": DEPOSIT_REFUND_STATUSES[3]},
		update_modified=False,
	)
	_sync_project_deposit_refund_mirror(project, bl_name)
	return get_project_deposit_refund_context(project) or {}


@frappe.whitelist()
def create_deposit_refund_from_project(
	project: str,
	amount: float,
	pay_from_account: str,
	pay_to_account: str,
	posting_date: str | None = None,
	party_type: str | None = None,
	party: str | None = None,
	cheque_no: str | None = None,
	cheque_date: str | None = None,
	user_remark: str | None = None,
) -> str:
	"""Create a draft refund Journal Entry from the Project (updates BL on submit)."""
	if not project or not frappe.db.exists("Project", project):
		frappe.throw(_("Project not found."))
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	bl_name = get_bill_of_lading_for_project(project)
	if not bl_name:
		frappe.throw(_("This project has no linked Bill of Lading."))
	return create_deposit_refund_from_bl(
		bill_of_lading=bl_name,
		amount=amount,
		pay_from_account=pay_from_account,
		pay_to_account=pay_to_account,
		posting_date=posting_date,
		party_type=party_type,
		party=party,
		cheque_no=cheque_no,
		cheque_date=cheque_date,
		user_remark=user_remark,
	)


@frappe.whitelist()
def get_project_deposit_refund_defaults(project: str) -> dict:
	bl_name = get_bill_of_lading_for_project(project or "")
	if not bl_name:
		frappe.throw(_("This project has no linked Bill of Lading."))
	return get_bl_deposit_refund_defaults(bl_name)


@frappe.whitelist()
def create_deposit_credit_note_for_project(project: str) -> str:
	bl_name = get_bill_of_lading_for_project(project or "")
	if not bl_name:
		frappe.throw(_("This project has no linked Bill of Lading."))
	return create_deposit_credit_note_for_bl(bl_name)


@frappe.whitelist()
def get_deposit_bl_for_task(task_name: str) -> dict | None:
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(_("Task not found."))
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	project = frappe.db.get_value("Task", task_name, "project")
	return get_deposit_bl_for_project(project) if project else None


@frappe.whitelist()
def set_bl_deposit_payer(task_name: str, payer: str) -> dict:
	"""Finance confirms who pays the container deposit (Agent / Customer / Company)."""
	if payer not in DEPOSIT_PAYERS:
		frappe.throw(_("Select a valid deposit payer: Agent, Customer, or Company."))
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(_("Task not found."))
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	bl_name = get_bill_of_lading_for_project(task.project or "")
	if not bl_name:
		frappe.throw(_("No Bill of Lading linked to this project."))
	bl = frappe.get_doc("Bill of Lading", bl_name)
	if not is_container_deposit_bl(bl):
		frappe.throw(_("This Bill of Lading does not have a container deposit arrangement."))

	updates = {"deposit_payer": payer}
	if bl.meta.has_field("deposit_company_invoice_pending"):
		updates["deposit_company_invoice_pending"] = 1 if payer == "Company" else 0
	if payer == "Agent" and bl.meta.has_field("deposit_refund_status"):
		updates["deposit_refund_status"] = ""

	frappe.db.set_value("Bill of Lading", bl_name, updates, update_modified=False)
	if task.meta.has_field("custom_deposit_payer"):
		frappe.db.set_value("Task", task_name, "custom_deposit_payer", payer, update_modified=False)
	sync_bl_deposit_to_shipping_line_tasks(bl)
	return get_deposit_bl_for_project(task.project) or {}


def validate_shipping_line_deposit_payments(task) -> None:
	"""Block Shipping Line finance completion until deposit payer + payment rules are met."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_FINANCE_FIELD
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_shipping_line_finance_payment_task,
	)

	seq = int(task.get("custom_sequence_no") or 0)
	if not is_shipping_line_finance_payment_task(seq) or not task.project:
		return
	bl = get_deposit_bl_for_project(task.project)
	if not bl:
		return

	payer = bl_deposit_payer(bl) or (task.get("custom_deposit_payer") or "").strip()
	if not payer:
		frappe.throw(
			_(
				"Confirm who pays the container deposit on this task "
				"(<b>Agent</b>, <b>Customer</b>, or <b>Company</b>) before completing."
			)
		)

	if flt(bl.get("deposit_amount")) <= 0:
		frappe.throw(
			_(
				"Enter container deposit amounts on Bill of Lading <b>{0}</b> before completing."
			).format(bl.get("bl_number") or bl.get("name"))
		)

	if (bl.get("deposit_payment_status") or "") == DEPOSIT_PAYMENT_STATUSES[1]:
		frappe.throw(
			_(
				"Record the container deposit payment (Journal Entry) for Bill of Lading "
				"<b>{0}</b> before completing this task."
			).format(bl.get("bl_number") or bl.get("name"))
		)

	if payer == "Customer":
		si = bl.get("deposit_sales_invoice")
		if not si or frappe.db.get_value("Sales Invoice", si, "docstatus") != 1:
			frappe.throw(
				_(
					"Create and submit the Sales Invoice (Shipping Line charges + container deposit) "
					"for Bill of Lading <b>{0}</b> before completing."
				).format(bl.get("bl_number") or bl.get("name"))
			)


def _resolve_company_and_project(task) -> tuple[str, str | None]:
	company = task.company or (
		frappe.db.get_value("Project", task.project, "company") if task.project else None
	)
	if not company:
		frappe.throw(_("Could not determine the Company for this payment."))
	return company, task.project


def _validate_accounts(company: str, pay_from_account: str, pay_to_account: str) -> None:
	if not pay_from_account or not pay_to_account:
		frappe.throw(_("Select both the <b>Pay From</b> and <b>Pay To</b> accounts."))
	if pay_from_account == pay_to_account:
		frappe.throw(_("<b>Pay From</b> and <b>Pay To</b> accounts must be different."))
	for acc in (pay_from_account, pay_to_account):
		acc_company = frappe.db.get_value("Account", acc, "company")
		if acc_company and acc_company != company:
			frappe.throw(
				_("Account <b>{0}</b> does not belong to company <b>{1}</b>.").format(acc, company)
			)


def _party_requirements(pay_from_account: str, pay_to_account: str, party_type, party):
	pay_to_type = frappe.db.get_value("Account", pay_to_account, "account_type")
	pay_from_type = frappe.db.get_value("Account", pay_from_account, "account_type")
	party_side = None
	if pay_to_type in ("Payable", "Receivable"):
		party_side = "to"
	elif pay_from_type in ("Payable", "Receivable"):
		party_side = "from"
	if party_side and not (party and party_type):
		frappe.throw(
			_("A selected account is a <b>Party</b> account - choose a Party Type and Party.")
		)
	return party_side


def _build_journal_entry(
	*,
	company: str,
	project: str | None,
	task_name: str | None,
	bill_of_lading: str,
	amount: float,
	pay_from_account: str,
	pay_to_account: str,
	posting_date,
	party_type=None,
	party=None,
	cheque_no=None,
	cheque_date=None,
	user_remark: str | None = None,
	deposit_kind: str,
) -> frappe.model.document.Document:
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	from_currency = (
		frappe.db.get_value("Account", pay_from_account, "account_currency") or company_currency
	)
	to_currency = (
		frappe.db.get_value("Account", pay_to_account, "account_currency") or company_currency
	)

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	if from_currency != company_currency or to_currency != company_currency:
		je.multi_currency = 1
	je.posting_date = getdate(posting_date) if posting_date else today()
	je.user_remark = user_remark or ""
	if cheque_no:
		je.cheque_no = cheque_no
	if cheque_date:
		je.cheque_date = getdate(cheque_date)
	if je.meta.has_field("custom_cgm_source_task") and task_name:
		je.custom_cgm_source_task = task_name
	if je.meta.has_field("custom_cgm_source_bill_of_lading"):
		je.custom_cgm_source_bill_of_lading = bill_of_lading
	if je.meta.has_field("custom_cgm_deposit_entry_kind"):
		je.custom_cgm_deposit_entry_kind = deposit_kind

	debit_row = {
		"account": pay_to_account,
		"debit_in_account_currency": amount,
		"project": project,
		"user_remark": je.user_remark,
	}
	credit_row = {
		"account": pay_from_account,
		"credit_in_account_currency": amount,
		"project": project,
		"user_remark": je.user_remark,
	}
	party_side = _party_requirements(pay_from_account, pay_to_account, party_type, party)
	if party_side == "to":
		debit_row.update({"party_type": party_type, "party": party})
	elif party_side == "from":
		credit_row.update({"party_type": party_type, "party": party})

	je.append("accounts", debit_row)
	je.append("accounts", credit_row)
	je.insert()
	return je


def _link_outbound_je(bl_name: str, je_name: str) -> None:
	meta = _bl_meta()
	if meta.has_field("deposit_payment_journal_entry"):
		frappe.db.set_value(
			"Bill of Lading",
			bl_name,
			"deposit_payment_journal_entry",
			je_name,
			update_modified=False,
		)
	bl = frappe.get_doc("Bill of Lading", bl_name)
	refresh_bl_deposit_payment_status(bl)
	bl.db_set("deposit_payment_status", bl.deposit_payment_status, update_modified=False)


def _link_refund_je_draft(bl_name: str, je_name: str) -> None:
	meta = _bl_meta()
	if meta.has_field("deposit_refund_journal_entry"):
		frappe.db.set_value(
			"Bill of Lading",
			bl_name,
			"deposit_refund_journal_entry",
			je_name,
			update_modified=False,
		)


def _mark_refund_received(bl_name: str) -> None:
	meta = _bl_meta()
	updates = {"deposit_refund_status": DEPOSIT_REFUND_STATUSES[2]}  # Received
	if meta.has_field("deposit_refund_applied_on"):
		updates["deposit_refund_applied_on"] = today()
	frappe.db.set_value("Bill of Lading", bl_name, updates, update_modified=False)
	project = _project_for_bl(bl_name)
	if project:
		_sync_project_deposit_refund_mirror(project, bl_name)


@frappe.whitelist()
def create_deposit_payment_from_task(
	task_name: str,
	amount: float | None = None,
	pay_from_account: str | None = None,
	pay_to_account: str | None = None,
	posting_date: str | None = None,
	party_type: str | None = None,
	party: str | None = None,
	cheque_no: str | None = None,
	cheque_date: str | None = None,
	user_remark: str | None = None,
	# Legacy kwargs ignored (per-container payment removed)
	container_tracker: str | None = None,
) -> str:
	"""Create one draft Journal Entry for the BL container deposit total."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(_("Task not found."))
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	frappe.has_permission("Journal Entry", ptype="create", throw=True)

	task = frappe.get_doc("Task", task_name)
	bl_info = get_deposit_bl_for_project(task.project or "")
	if not bl_info:
		frappe.throw(_("No Bill of Lading with a container deposit on this project."))
	bl_name = bl_info["name"]

	if bl_info.get("deposit_payment_journal_entry") and frappe.db.get_value(
		"Journal Entry", bl_info.deposit_payment_journal_entry, "docstatus"
	) != 2:
		frappe.throw(
			_("A deposit Journal Entry is already linked for Bill of Lading <b>{0}</b>.").format(
				bl_info.get("bl_number") or bl_name
			)
		)

	pay_amount = flt(amount if amount is not None else bl_info.get("deposit_amount"))
	if pay_amount <= 0:
		frappe.throw(_("Enter a payment <b>Amount</b> greater than zero."))

	company, project = _resolve_company_and_project(task)
	_validate_accounts(company, pay_from_account, pay_to_account)

	default_deposit = get_container_deposit_account(company)
	if default_deposit and pay_to_account != default_deposit:
		frappe.msgprint(
			_("Pay To account is not the configured Container Deposit account."),
			indicator="orange",
			alert=True,
		)

	remark = user_remark or _("Container deposit - BL {0} ({1})").format(
		bl_info.get("bl_number") or bl_name, task.subject
	)

	je = _build_journal_entry(
		company=company,
		project=project,
		task_name=task.name,
		bill_of_lading=bl_name,
		amount=pay_amount,
		pay_from_account=pay_from_account,
		pay_to_account=pay_to_account,
		posting_date=posting_date,
		party_type=party_type,
		party=party,
		cheque_no=cheque_no,
		cheque_date=cheque_date,
		user_remark=remark,
		deposit_kind=DEPOSIT_JE_KIND_OUTBOUND,
	)
	_link_outbound_je(bl_name, je.name)
	return je.name


@frappe.whitelist()
def create_deposit_refund_from_bl(
	bill_of_lading: str,
	amount: float,
	pay_from_account: str,
	pay_to_account: str,
	posting_date: str | None = None,
	party_type: str | None = None,
	party: str | None = None,
	cheque_no: str | None = None,
	cheque_date: str | None = None,
	user_remark: str | None = None,
) -> str:
	"""Create a draft Journal Entry to record BL deposit refund (Dr bank / Cr deposit asset)."""
	if not bill_of_lading or not frappe.db.exists("Bill of Lading", bill_of_lading):
		frappe.throw(_("Bill of Lading not found."))
	frappe.has_permission("Bill of Lading", ptype="read", doc=bill_of_lading, throw=True)
	frappe.has_permission("Journal Entry", ptype="create", throw=True)

	bl = frappe.get_doc("Bill of Lading", bill_of_lading)
	if not is_container_deposit_bl(bl):
		frappe.throw(_("This Bill of Lading does not have a container deposit arrangement."))
	if not bl_is_refundable(bl):
		frappe.throw(_("This container deposit is not refundable (Agent-paid deposits are not refunded)."))
	if bl.get("deposit_payment_status") != DEPOSIT_PAYMENT_STATUSES[2]:
		frappe.throw(_("Deposit must be paid before recording a refund."))
	if bl.get("deposit_refund_journal_entry") and frappe.db.get_value(
		"Journal Entry", bl.deposit_refund_journal_entry, "docstatus"
	) != 2:
		frappe.throw(_("A refund Journal Entry is already linked for this Bill of Lading."))

	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Enter a refund <b>Amount</b> greater than zero."))

	project = frappe.db.get_value("Project", {"custom_bill_of_lading": bill_of_lading}, "name")
	company = frappe.db.get_value("Project", project, "company") if project else None
	if not company:
		frappe.throw(_("Could not determine the Company for this refund."))
	_validate_accounts(company, pay_from_account, pay_to_account)

	remark = user_remark or _("Container deposit refund - BL {0}").format(
		bl.bl_number or bl.name
	)

	je = _build_journal_entry(
		company=company,
		project=project,
		task_name=None,
		bill_of_lading=bill_of_lading,
		amount=amount,
		pay_from_account=pay_from_account,
		pay_to_account=pay_to_account,
		posting_date=posting_date,
		party_type=party_type,
		party=party,
		cheque_no=cheque_no,
		cheque_date=cheque_date,
		user_remark=remark,
		deposit_kind=DEPOSIT_JE_KIND_REFUND,
	)
	_link_refund_je_draft(bill_of_lading, je.name)
	return je.name


def sync_deposit_status_from_journal_entry(je, method=None) -> None:
	"""Refresh BL deposit fields when a linked Journal Entry changes."""
	if not is_deposit_journal_entry(je):
		return

	bl_name = je.get("custom_cgm_source_bill_of_lading")
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return

	kind = (je.get("custom_cgm_deposit_entry_kind") or "").strip()
	docstatus = int(je.docstatus or 0)
	meta = _bl_meta()

	if kind == DEPOSIT_JE_KIND_OUTBOUND or (
		not kind and meta.has_field("deposit_payment_journal_entry")
	):
		if docstatus == 1:
			if meta.has_field("deposit_payment_journal_entry"):
				frappe.db.set_value(
					"Bill of Lading",
					bl_name,
					"deposit_payment_journal_entry",
					je.name,
					update_modified=False,
				)
		elif docstatus == 2:
			current = frappe.db.get_value(
				"Bill of Lading", bl_name, "deposit_payment_journal_entry"
			)
			if current == je.name and meta.has_field("deposit_payment_journal_entry"):
				frappe.db.set_value(
					"Bill of Lading",
					bl_name,
					"deposit_payment_journal_entry",
					None,
					update_modified=False,
				)

	if kind == DEPOSIT_JE_KIND_REFUND:
		if docstatus == 1:
			if meta.has_field("deposit_refund_journal_entry"):
				frappe.db.set_value(
					"Bill of Lading",
					bl_name,
					"deposit_refund_journal_entry",
					je.name,
					update_modified=False,
				)
			_mark_refund_received(bl_name)
		elif docstatus == 2:
			current = frappe.db.get_value(
				"Bill of Lading", bl_name, "deposit_refund_journal_entry"
			)
			if current == je.name:
				updates = {"deposit_refund_status": DEPOSIT_REFUND_STATUSES[0]}
				if meta.has_field("deposit_refund_journal_entry"):
					updates["deposit_refund_journal_entry"] = None
				frappe.db.set_value("Bill of Lading", bl_name, updates, update_modified=False)

	bl = frappe.get_doc("Bill of Lading", bl_name)
	refresh_bl_deposit_payment_status(bl)
	updates = {"deposit_payment_status": bl.deposit_payment_status}
	if bl.meta.has_field("deposit_amount"):
		updates["deposit_amount"] = bl.deposit_amount
	bl.db_set(updates, update_modified=False)


def _settings_reminder_config() -> dict:
	settings = get_cgm_shipping_settings() or frappe._dict()
	return {
		"remind_after": cint(settings.get("deposit_refund_remind_after") or 0),
		"remind_after_unit": (settings.get("deposit_refund_remind_after_unit") or "Days").strip(),
		"repeat_every": cint(settings.get("deposit_refund_repeat_every") or 0) or 24,
		"repeat_unit": (settings.get("deposit_refund_repeat_unit") or "Hours").strip(),
		"stop_after_days": cint(settings.get("deposit_refund_stop_after_days") or 0) or 14,
	}


def _to_timedelta(value: int, unit: str) -> timedelta:
	if (unit or "Days").strip().lower().startswith("hour"):
		return timedelta(hours=max(0, value))
	return timedelta(days=max(0, value))


def _deposit_reminder_due(bl, cfg: dict, now: datetime) -> bool:
	if (bl.get("deposit_refund_status") or "") != DEPOSIT_REFUND_STATUSES[0]:
		return False
	return_date = bl.get("deposit_return_date")
	if not return_date:
		return False
	start = get_datetime(return_date)
	if cfg["remind_after"] > 0:
		start = start + _to_timedelta(cfg["remind_after"], cfg["remind_after_unit"])
	if now < start:
		return False
	stop_at = get_datetime(return_date) + timedelta(days=cfg["stop_after_days"])
	if now > stop_at:
		return False
	last = bl.get("deposit_refund_last_reminded_on")
	if not last:
		return True
	repeat_delta = _to_timedelta(cfg["repeat_every"], cfg["repeat_unit"])
	return get_datetime(last) + repeat_delta <= now


@frappe.whitelist()
def get_bl_deposit_refund_defaults(bill_of_lading: str) -> dict:
	if not bill_of_lading or not frappe.db.exists("Bill of Lading", bill_of_lading):
		frappe.throw(_("Bill of Lading not found."))
	frappe.has_permission("Bill of Lading", ptype="read", doc=bill_of_lading, throw=True)
	bl = frappe.get_doc("Bill of Lading", bill_of_lading)
	project = frappe.db.get_value("Project", {"custom_bill_of_lading": bill_of_lading}, "name")
	company = frappe.db.get_value("Project", project, "company") if project else None
	return {
		"deposit_account": get_container_deposit_account(company) if company else None,
		"amount": flt(bl.get("deposit_amount")),
	}


@frappe.whitelist()
def get_deposit_payment_defaults(task_name: str) -> dict:
	"""Default accounts and BL deposit summary for Make Deposit Payment."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(_("Task not found."))
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	company = task.company
	if not company and task.project:
		company = frappe.db.get_value("Project", task.project, "company")
	bl = get_deposit_bl_for_project(task.project or "") if task.project else None
	return {
		"deposit_account": get_container_deposit_account(company) if company else None,
		"bill_of_lading": bl,
		"amount": flt(bl.get("deposit_amount")) if bl else 0,
	}


def _shipping_line_charges_and_invoice_total(task, bl: dict | None) -> tuple[float, float]:
	"""Return (charges_amount, invoice_total) for Shipping Line payment defaults."""
	if bl and bl.get("deposit_sales_invoice") and frappe.db.exists(
		"Sales Invoice", bl.deposit_sales_invoice
	):
		si = frappe.get_doc("Sales Invoice", bl.deposit_sales_invoice)
		deposit_item = get_container_deposit_sales_item(si.company)
		charges_total = 0.0
		line_total = 0.0
		has_deposit_line = False
		for row in si.items:
			line_amt = flt(row.amount)
			line_total += line_amt
			if deposit_item and row.item_code == deposit_item:
				has_deposit_line = True
				continue
			charges_total += line_amt
		invoice_total = flt(si.grand_total) or line_total
		if has_deposit_line and charges_total > 0:
			return charges_total, invoice_total
		return invoice_total, invoice_total

	company = task.company
	if not company and task.project:
		company = frappe.db.get_value("Project", task.project, "company")
	_, amount = _shipping_line_sales_item_for_task(task, company or "")
	amount = flt(amount)
	return amount, amount


@frappe.whitelist()
def get_shipping_line_expense_payment_defaults(
	task_name: str, finance_line_name: str | None = None
) -> dict:
	"""Defaults for Shipping Line expense JE (invoice total minus BL container deposit)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_FINANCE_FIELD
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_shipping_line_finance_payment_task,
	)

	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(_("Task not found."))
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	task = frappe.get_doc("Task", task_name)
	seq = int(task.get("custom_sequence_no") or 0)
	if not is_shipping_line_finance_payment_task(seq):
		frappe.throw(_("This task is not a Shipping Line finance payment step."))

	bl = get_deposit_bl_for_project(task.project or "") if task.project else None
	split_deposit = bool(
		bl
		and bl_deposit_arrangement(bl) == DEPOSIT_ARRANGEMENT_CONTAINER
		and flt(bl.get("deposit_amount")) > 0
	)
	if finance_line_name:
		for row in task.get(TASK_FINANCE_FIELD) or []:
			if row.name == finance_line_name and cint(row.get("is_amendment")):
				split_deposit = False
				break

	deposit_total = flt(bl.get("deposit_amount")) if bl and split_deposit else 0.0
	charges_amount, invoice_total = _shipping_line_charges_and_invoice_total(task, bl)

	if split_deposit and charges_amount > 0:
		expense_amount = charges_amount
	elif split_deposit and invoice_total > 0:
		expense_amount = max(0.0, invoice_total - deposit_total)
	elif invoice_total > 0:
		expense_amount = invoice_total
	else:
		expense_amount = 0.0

	help_html = ""
	default_remark = ""
	if split_deposit:
		bl_label = (bl.get("bl_number") or bl.get("name") or "").strip()
		if expense_amount > 0 and invoice_total > 0:
			help_html = _(
				"The shipping line invoice includes a container deposit. "
				"This Journal Entry records <b>shipping line charges only</b> "
				"({0:,.2f} of {1:,.2f}). Record the deposit ({2:,.2f}) separately using "
				"<b>Make Deposit Payment</b>{3}."
			).format(
				expense_amount,
				invoice_total,
				deposit_total,
				f" for BL {bl_label}" if bl_label else "",
			)
		else:
			help_html = _(
				"The shipping line invoice includes a container deposit ({0:,.2f}). "
				"Enter the <b>charges portion only</b> (invoice total minus deposit). "
				"Record the deposit separately using <b>Make Deposit Payment</b>{1}."
			).format(deposit_total, f" for BL {bl_label}" if bl_label else "")
		default_remark = _("Shipping Line charges (excluding container deposit)")

	return {
		"amount": expense_amount,
		"invoice_total": invoice_total,
		"deposit_total": deposit_total,
		"split_deposit": split_deposit,
		"help_html": help_html,
		"default_remark": default_remark,
		"bill_of_lading": bl,
	}


def send_deposit_refund_reminders() -> int:
	"""Scheduled job: remind Finance to collect BL container deposit refunds."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CONTAINER_DEPOSIT_REFUND_REMINDER,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
		send_notification,
	)

	meta = _bl_meta()
	if not meta.has_field("deposit_refund_status"):
		return 0

	cfg = _settings_reminder_config()
	if cfg["remind_after"] <= 0 and cfg["repeat_every"] <= 0:
		return 0

	fields = [
		"name",
		"bl_number",
		"deposit_amount",
		"deposit_refund_status",
		"deposit_return_date",
	]
	if meta.has_field("deposit_refund_last_reminded_on"):
		fields.append("deposit_refund_last_reminded_on")

	now = now_datetime()
	sent = 0
	for row in frappe.get_all(
		"Bill of Lading",
		filters={
			"deposit_arrangement": DEPOSIT_ARRANGEMENT_CONTAINER,
			"deposit_payment_status": DEPOSIT_PAYMENT_STATUSES[2],
			"deposit_refund_status": DEPOSIT_REFUND_STATUSES[0],
		},
		fields=fields + (["deposit_payer"] if meta.has_field("deposit_payer") else []),
	):
		if meta.has_field("deposit_payer") and (row.get("deposit_payer") or "") == "Agent":
			continue
		if not bl_is_refundable(row):
			continue
		if not _deposit_reminder_due(row, cfg, now):
			continue
		bl = frappe.get_doc("Bill of Lading", row.name)
		result = send_notification(CONTAINER_DEPOSIT_REFUND_REMINDER, bl, audience="Finance")
		if result.get("emails_sent") or result.get("notified"):
			sent += 1
		if meta.has_field("deposit_refund_last_reminded_on"):
			bl.db_set("deposit_refund_last_reminded_on", now, update_modified=False)
	return sent


def get_container_deposit_sales_item(company: str | None = None) -> str:
	settings = get_cgm_shipping_settings()
	if settings and settings.meta.has_field("container_deposit_sales_item"):
		item = (settings.get("container_deposit_sales_item") or "").strip()
		if item and frappe.db.exists("Item", item):
			return item
	for name in ("Container Deposit", "CGM-CONTAINER-DEPOSIT"):
		if frappe.db.exists("Item", name):
			return name
	return ""


def _shipping_line_sales_item_for_task(task, company: str) -> tuple[str, float]:
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_FINANCE_FIELD

	amount = 0.0
	item_code = ""
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if (row.get("line_type") or "") != "Invoice":
			continue
		if (row.get("payment_item") or row.get("line_label") or "").find("Shipping Line") < 0:
			continue
		item_code = (row.get("item_code") or "").strip()
		amount = flt(row.get("amount"))
		break
	if item_code and frappe.db.get_value("Item", item_code, "is_sales_item"):
		return item_code, amount
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		get_purchase_item_for_payment_item,
	)

	fallback = get_purchase_item_for_payment_item("Shipping Line", company)
	if fallback and frappe.db.get_value("Item", fallback, "is_sales_item"):
		return fallback, amount
	for name in ("Shipping Line Charges", "CGM-SHIPPING-LINE"):
		if frappe.db.exists("Item", name) and frappe.db.get_value("Item", name, "is_sales_item"):
			return name, amount
	return fallback or "", amount


def _project_customer_and_company(project: str) -> tuple[str, str]:
	customer = frappe.db.get_value("Project", project, "customer")
	company = frappe.db.get_value("Project", project, "company")
	if not customer:
		frappe.throw(_("Project has no Customer - cannot create a Sales Invoice."))
	if not company:
		frappe.throw(_("Project has no Company - cannot create a Sales Invoice."))
	return customer, company


def _validate_customer_deposit_sales_invoice_task(task_name: str):
	"""Shared guards for customer-path container deposit Sales Invoice."""
	if not task_name or not frappe.db.exists("Task", task_name):
		frappe.throw(_("Task not found."))
	frappe.has_permission("Task", ptype="read", doc=task_name, throw=True)
	frappe.has_permission("Sales Invoice", ptype="create", throw=True)

	task = frappe.get_doc("Task", task_name)
	if not task.project:
		frappe.throw(_("Task has no Project."))
	bl = get_deposit_bl_for_project(task.project)
	if not bl:
		frappe.throw(_("No container deposit on the linked Bill of Lading."))
	if bl_deposit_payer(bl) and bl_deposit_payer(bl) != "Customer":
		frappe.throw(_("Deposit payer is not Customer - use the correct payment path."))
	if bl.get("deposit_sales_invoice"):
		frappe.throw(_("A Sales Invoice is already linked for this deposit."))

	deposit_total = flt(bl.get("deposit_amount"))
	if deposit_total <= 0:
		frappe.throw(_("Enter container deposit amounts on the Bill of Lading first."))

	deposit_item = get_container_deposit_sales_item(
		frappe.db.get_value("Project", task.project, "company")
	)
	if not deposit_item:
		frappe.throw(
			_("Configure <b>Container Deposit Sales Item</b> in CGM Shipping Settings, or create an Item.")
		)
	return task, bl


def _build_customer_deposit_sales_invoice_doc(task, bl, shipping_line_amount: float | None = None):
	"""Build an unsaved Sales Invoice for Shipping Line charges + container deposit."""
	customer, company = _project_customer_and_company(task.project)
	currency = bl.get("deposit_currency") or frappe.get_cached_value("Company", company, "default_currency")
	deposit_total = flt(bl.get("deposit_amount"))
	deposit_item = get_container_deposit_sales_item(company)

	sl_item, sl_amount = _shipping_line_sales_item_for_task(task, company)
	if shipping_line_amount is not None:
		sl_amount = flt(shipping_line_amount)

	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	si.company = company
	si.project = task.project
	si.currency = currency
	if si.meta.has_field("custom_cgm_source_task"):
		si.custom_cgm_source_task = task.name
	if si.meta.has_field("custom_cgm_source_bill_of_lading"):
		si.custom_cgm_source_bill_of_lading = bl["name"]

	if sl_item and sl_amount > 0:
		si.append(
			"items",
			{
				"item_code": sl_item,
				"qty": 1,
				"rate": sl_amount,
				"description": _("Shipping Line Charges"),
			},
		)
	si.append(
		"items",
		{
			"item_code": deposit_item,
			"qty": 1,
			"rate": deposit_total,
			"description": _("Container Deposit - BL {0}").format(bl.get("bl_number") or bl.get("name")),
		},
	)
	si.run_method("set_missing_values")
	si.run_method("calculate_taxes_and_totals")
	return si


def link_deposit_sales_invoice_to_bl(
	sales_invoice: str, bill_of_lading: str, task_name: str | None = None
) -> None:
	"""Link a saved Sales Invoice to the Bill of Lading container deposit."""
	if not sales_invoice or not bill_of_lading:
		return
	if not frappe.db.exists("Bill of Lading", bill_of_lading):
		return
	if cint(frappe.db.get_value("Sales Invoice", sales_invoice, "is_return")):
		return

	existing = frappe.db.get_value("Bill of Lading", bill_of_lading, "deposit_sales_invoice")
	if existing and existing != sales_invoice:
		frappe.throw(
			_("Bill of Lading <b>{0}</b> already has deposit Sales Invoice <b>{1}</b>.").format(
				bill_of_lading, existing
			)
		)

	frappe.db.set_value(
		"Bill of Lading",
		bill_of_lading,
		{"deposit_sales_invoice": sales_invoice, "deposit_payer": "Customer"},
		update_modified=False,
	)
	if task_name and frappe.get_meta("Task").has_field("custom_deposit_payer"):
		frappe.db.set_value(
			"Task", task_name, "custom_deposit_payer", "Customer", update_modified=False
		)


@frappe.whitelist()
def make_customer_deposit_sales_invoice(task_name: str) -> dict:
	"""Open a standard draft Sales Invoice prefilled with SL charges + container deposit."""
	task, bl = _validate_customer_deposit_sales_invoice_task(task_name)
	si = _build_customer_deposit_sales_invoice_doc(task, bl)
	return si.as_dict()


@frappe.whitelist()
def create_customer_sl_sales_invoice_with_deposit(
	task_name: str,
	shipping_line_amount: float | None = None,
) -> str:
	"""Customer path: create and save a draft Sales Invoice (legacy API)."""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	task, bl = _validate_customer_deposit_sales_invoice_task(task_name)
	si = _build_customer_deposit_sales_invoice_doc(task, bl, shipping_line_amount)
	if shipping_line_amount is not None and not any(
		flt(row.rate) > 0 and (row.description or "").find("Shipping Line") >= 0
		for row in si.get("items") or []
	):
		frappe.msgprint(
			_("Shipping Line charge amount is zero - add or adjust the line on the Sales Invoice."),
			indicator="orange",
		)
	si.insert()
	link_deposit_sales_invoice_to_bl(si.name, bl["name"], task.name)
	return si.name


@frappe.whitelist()
def create_company_deposit_sales_invoice_for_project(project: str) -> str:
	"""Company path: invoice customer at project end for SL charges + container deposit."""
	if not project or not frappe.db.exists("Project", project):
		frappe.throw(_("Project not found."))
	frappe.has_permission("Project", ptype="write", doc=project, throw=True)
	frappe.has_permission("Sales Invoice", ptype="create", throw=True)

	bl = get_deposit_bl_for_project(project)
	if not bl:
		frappe.throw(_("No container deposit on the linked Bill of Lading."))
	if bl_deposit_payer(bl) != "Company":
		frappe.throw(_("Deposit payer is not Company."))
	if bl.get("deposit_sales_invoice"):
		frappe.throw(_("A Sales Invoice is already linked for this deposit."))

	customer, company = _project_customer_and_company(project)
	currency = bl.get("deposit_currency") or frappe.get_cached_value("Company", company, "default_currency")
	deposit_total = flt(bl.get("deposit_amount"))
	deposit_item = get_container_deposit_sales_item(company)
	if not deposit_item:
		frappe.throw(_("Configure Container Deposit Sales Item in CGM Shipping Settings."))

	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	si.company = company
	si.project = project
	si.currency = currency
	si.append(
		"items",
		{
			"item_code": deposit_item,
			"qty": 1,
			"rate": deposit_total,
			"description": _("Container Deposit (Company paid) - BL {0}").format(
				bl.get("bl_number") or bl.get("name")
			),
		},
	)
	si.insert()
	updates = {"deposit_sales_invoice": si.name, "deposit_company_invoice_pending": 0}
	frappe.db.set_value("Bill of Lading", bl["name"], updates, update_modified=False)
	return si.name


@frappe.whitelist()
def create_deposit_credit_note_for_bl(bill_of_lading: str) -> str:
	"""Credit note for container deposit only (after SL refunds CGM)."""
	if not bill_of_lading or not frappe.db.exists("Bill of Lading", bill_of_lading):
		frappe.throw(_("Bill of Lading not found."))
	frappe.has_permission("Bill of Lading", ptype="read", doc=bill_of_lading, throw=True)
	frappe.has_permission("Sales Invoice", ptype="create", throw=True)

	bl = frappe.db.get_value(
		"Bill of Lading",
		bill_of_lading,
		[
			"deposit_sales_invoice",
			"deposit_credit_note",
			"deposit_amount",
			"deposit_payer",
			"deposit_arrangement",
			"bl_number",
		],
		as_dict=True,
	)
	if not bl or bl_deposit_arrangement(bl) != DEPOSIT_ARRANGEMENT_CONTAINER:
		frappe.throw(_("This Bill of Lading does not have a container deposit."))
	if bl.get("deposit_payer") != "Customer":
		frappe.throw(_("Credit notes apply only when the Customer paid the deposit."))
	if bl.get("deposit_credit_note"):
		frappe.throw(_("A deposit credit note is already linked."))
	if not bl.get("deposit_sales_invoice"):
		frappe.throw(_("Link a customer Sales Invoice before creating a deposit credit note."))

	from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

	return_si = make_sales_return(bl.deposit_sales_invoice)
	cn = frappe.get_doc(return_si)
	deposit_item = get_container_deposit_sales_item()
	deposit_amount = flt(bl.deposit_amount)
	# Keep only the container deposit line (returns require negative qty).
	keep = []
	for row in cn.items:
		is_deposit_line = deposit_item and row.item_code == deposit_item
		if not deposit_item:
			is_deposit_line = abs(flt(row.rate)) == deposit_amount
		if is_deposit_line:
			row.qty = -1
			row.rate = deposit_amount
			keep.append(row)
	if not keep:
		frappe.throw(
			_("Could not find the container deposit line on the original Sales Invoice.")
		)
	cn.set("items", keep)
	cn.is_return = 1
	cn.return_against = bl.deposit_sales_invoice
	cn.run_method("set_missing_values")
	cn.run_method("calculate_taxes_and_totals")
	cn.insert()
	frappe.db.set_value(
		"Bill of Lading", bill_of_lading, "deposit_credit_note", cn.name, update_modified=False
	)
	return cn.name


# ---------------------------------------------------------------------------
# Backward-compatible aliases (tests / older call sites)
# ---------------------------------------------------------------------------


def refresh_deposit_payment_status(doc) -> None:
	"""Alias: refresh status on a Bill of Lading document."""
	refresh_bl_deposit_payment_status(doc)


def maybe_start_deposit_refund_tracking(doc) -> None:
	"""Alias: start refund tracking on a Bill of Lading document."""
	maybe_start_bl_deposit_refund_tracking(doc)


@frappe.whitelist()
def get_deposit_containers_for_task(task_name: str) -> list[dict]:
	"""Legacy API: return BL deposit container breakdown for the task's project."""
	bl = get_deposit_bl_for_task(task_name)
	if not bl:
		return []
	return bl.get("containers") or []
