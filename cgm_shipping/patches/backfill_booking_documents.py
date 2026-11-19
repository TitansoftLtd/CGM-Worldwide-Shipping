"""Fill Booking rows that never received their booking's attachment.

Why: the file carried from a Booking Confirmation to its Opportunity only at the
moment of submit, and never again. On production 4 of the 5 submitted bookings
holding a file had an empty Booking row, so the file never reached the project
either.

What: for each submitted booking with an attachment, fills the Opportunity's
Booking row when that row has no file. Never replaces a file somebody attached,
and leaves row order alone.

Idempotent. One-time - retire per docs/guides/patches.md.
"""

import frappe


def execute():
	from cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation.booking_confirmation import (
		backfill_booking_documents,
	)

	if not frappe.db.exists("DocType", "Booking Confirmation"):
		return
	filled = backfill_booking_documents()
	frappe.db.commit()
	print(f"backfill_booking_documents: filled {filled} Booking row(s)")
