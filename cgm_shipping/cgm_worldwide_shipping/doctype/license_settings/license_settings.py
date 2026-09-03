# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class LicenseSettings(Document):
	def validate(self):
		self.validate_reminder_periods()

	def validate_reminder_periods(self):
		if not self.enable_notifications:
			return

		seen = set()
		for row in self.reminder_periods:
			days = cint(row.days_before)
			if days <= 0:
				frappe.throw(
					_("Row {0}: Days Before Expiry must be greater than zero.").format(row.idx),
					title=_("Invalid Notification Period"),
				)
			if days in seen:
				frappe.throw(
					_("Row {0}: A reminder for {1} days before expiry is already set up.").format(
						row.idx, days
					),
					title=_("Duplicate Notification Period"),
				)
			seen.add(days)

		if (self.notify_by_email or self.notify_in_app) and not self.reminder_periods:
			frappe.msgprint(
				_("No notification periods are set up, so no expiry reminders will be sent."),
				indicator="orange",
				alert=True,
			)

	def on_update(self):
		frappe.clear_cache(doctype="License Settings")
		frappe.enqueue(
			"cgm_shipping.cgm_worldwide_shipping.customizations.license_reminders.refresh_license_statuses",
			queue="short",
			enqueue_after_commit=True,
		)
