"""Take cancelled Booking Confirmations off the Opportunities and Projects holding them.

Why: nothing released the link when a booking was cancelled, and Frappe refuses to
link a cancelled document. Add Bill of Lading seeds the booking from the shipment,
so the new Bill of Lading could not be saved at all: "Cannot link cancelled
document: Booking Confirmation: 2X40-7" (CRM-OPP-2026-00031 / PROJ-0028), which
also blocked entering the containers.

What: repoints each link at the booking's newest submitted amendment when it has
one, and clears it otherwise so the desk offers Add Booking Confirmation again.
Bills of Lading already linked to a cancelled booking are repointed the same way;
those with no replacement are left for someone to pick the right booking, since a
submitted Bill of Lading must not be edited blindly.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it. New cancellations are handled by
BookingConfirmation.on_cancel.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Booking Confirmation"):
		return
	from cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation.booking_confirmation import (
		BOOKING_LINK_FIELDS,
		newest_submitted_amendment,
	)

	cleared, moved = [], []
	for doctype, fieldname in BOOKING_LINK_FIELDS:
		if not frappe.db.has_column(doctype, fieldname):
			continue
		rows = frappe.db.sql(
			f"""
			SELECT holder.name, holder.{fieldname} AS booking
			FROM `tab{doctype}` holder
			JOIN `tabBooking Confirmation` bc ON bc.name = holder.{fieldname}
			WHERE bc.docstatus = 2
			""",
			as_dict=True,
		)
		for row in rows:
			replacement = newest_submitted_amendment(row.booking)
			frappe.db.set_value(doctype, row.name, fieldname, replacement, update_modified=False)
			frappe.clear_document_cache(doctype, row.name)
			(moved if replacement else cleared).append(f"{doctype} {row.name}")

	for row in frappe.db.sql(
		"""
		SELECT bl.name, bl.booking_confirmation AS booking
		FROM `tabBill of Lading` bl
		JOIN `tabBooking Confirmation` bc ON bc.name = bl.booking_confirmation
		WHERE bc.docstatus = 2
		""",
		as_dict=True,
	):
		replacement = newest_submitted_amendment(row.booking)
		if not replacement:
			continue
		frappe.db.set_value("Bill of Lading", row.name, "booking_confirmation", replacement, update_modified=False)
		frappe.clear_document_cache("Bill of Lading", row.name)
		moved.append(f"Bill of Lading {row.name}")

	if moved or cleared:
		print(
			f"Cancelled bookings released: {len(moved)} link(s) moved to an amendment, "
			f"{len(cleared)} cleared"
		)
