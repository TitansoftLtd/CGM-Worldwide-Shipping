"""Which Project fields an air shipment is not asked.

The hiding itself is declarative: each field carries NOT_AIR as its depends_on in
custom/project.json, so it shows in Customize Form and survives a migrate. The
lists here are the expected state, and test_air_field_visibility checks the JSON
still matches them.

Voyage Number is hidden on air with no replacement. The flight goes in Airline,
which is free text and is what the Air Waybill carries too. Hiding never deletes.
"""

from __future__ import annotations

import frappe

#: Breaks are listed too, so a heading goes with its fields.
SEA_ONLY_PROJECT_FIELDS: tuple[str, ...] = (
	# Carrier and routing only a vessel has.
	"custom_shipping_line",
	"custom_clearance_port",
	"custom_clearance_station",
	"custom_station_code",
	"custom_ecms_tracking_link",
	"custom_cargo_cutoff",
	# Air project names are client reference and quantity, no batch.
	"custom_batch_no",
	"custom_cfs_location",
	# Container tracker tab.
	"custom_container_tracker",
	"custom_section_container_tracking",
	"custom_container_tracking_html",
	"custom_container_tracker_mode",
	# Container deposit refund.
	"custom_section_container_deposit_refund",
	"custom_container_deposit_refund_status",
	"custom_container_deposit_refund_confirmed",
	"custom_column_break_deposit_refund",
	"custom_container_deposit_refund_confirmed_by",
	"custom_container_deposit_refund_confirmed_on",
	# Demurrage and port charges accrue against containers.
	"custom_section_container_charge_summary",
	"custom_demurrage_accrued_total",
	"custom_demurrage_accrued_total_display",
	"custom_demurrage_accrued_posted_total",
	"custom_demurrage_accrued_posted_total_display",
	"custom_kpa_port_accrued_total",
	"custom_kpa_port_accrued_total_display",
	"custom_kpa_port_accrued_posted_total",
	"custom_kpa_port_accrued_posted_total_display",
	# Berthing.
	"custom_section_before_berth",
	"custom_berth_phase",
	"custom_port_arrival_confirmed",
	"custom_port_arrival_confirmed_on",
	"custom_port_arrival_confirmed_by",
	"custom_column_break_before_berth",
)

#: Sea's journey number. Air has none; the flight goes in Airline.
SEA_ONLY_PROJECT_FIELDS = SEA_ONLY_PROJECT_FIELDS + ("custom_voyage_number",)

#: Shown only when the shipment flies. Both were already air-aware but each in
#: its own way, and Air Waybill named Air Import only, so Air Export never saw it.
AIR_ONLY_PROJECT_FIELDS: tuple[str, ...] = (
	"custom_airline",
	"custom_air_waybill",
)

#: Opportunity is where an air file starts, so it carries the same rule.
#: Port of Loading and Port of Discharge stay: on air they are the airports.
#: Cargo Type is left to the Shipment Type profile, which already hides it.
SEA_ONLY_OPPORTUNITY_FIELDS: tuple[str, ...] = (
	"custom_shipping_line",
	"custom_vessel",
	"custom_voyage_number",
	"custom_bill_of_lading",
	"custom_container_information",
	"custom_uses_container_tracking",
	"custom_clearance_station",
	"custom_station_code",
	"custom_cargo_cutoff",
	"custom_batch_no",
)

AIR_ONLY_OPPORTUNITY_FIELDS: tuple[str, ...] = (
	"custom_air_waybill",
	"custom_airline",
)

#: The depends_on each list carries in custom/project.json and custom/opportunity.json.
NOT_AIR = 'doc.custom_mode_of_transport != "Air" && !(doc.custom_shipment_type || "").startsWith("Air")'
IS_AIR = 'doc.custom_mode_of_transport == "Air" || (doc.custom_shipment_type || "").startsWith("Air")'

#: Sea defaults the system stamps on every Project. Only machine-set values:
#: what a person typed is kept, just hidden.
#:
#: Container Tracker Mode is hidden but not cleared. Shipment Type seeds it and
#: _backfill_project_container_tracker_modes puts it straight back, and with no
#: containers on an air job the stored value does nothing.
SEA_DEFAULTS_CLEARED_ON_AIR: dict[str, str] = {
	"custom_berth_phase": "Before Vessel Berth",
}


def project_is_air(doc) -> bool:
	"""Air by mode of transport, or by a shipment type that names it."""
	if not hasattr(doc, "get"):
		return False
	if str(doc.get("custom_mode_of_transport") or "").strip().lower() == "air":
		return True
	return str(doc.get("custom_shipment_type") or "").strip().lower().startswith("air")


def clear_sea_only_fields_on_air(doc, method=None) -> None:
	"""Drop sea defaults stamped before the mode was known."""
	if not project_is_air(doc):
		return
	for fieldname, stamped in SEA_DEFAULTS_CLEARED_ON_AIR.items():
		if not doc.meta.has_field(fieldname):
			continue
		current = doc.get(fieldname)
		if not current:
			continue
		if str(current).strip() != stamped:
			continue  # chosen deliberately
		doc.set(fieldname, None)


def clear_sea_defaults_on_existing_air_projects() -> int:
	"""Patch helper. Returns how many projects were tidied."""
	names = frappe.get_all(
		"Project",
		filters={"custom_mode_of_transport": "Air"},
		pluck="name",
	)
	touched = 0
	for name in names:
		updates = {}
		for fieldname, stamped in SEA_DEFAULTS_CLEARED_ON_AIR.items():
			current = frappe.db.get_value("Project", name, fieldname)
			if not current:
				continue
			if str(current).strip() != stamped:
				continue
			updates[fieldname] = None
		if updates:
			frappe.db.set_value("Project", name, updates, update_modified=False)
			touched += 1
	return touched
