# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, date_diff, format_date, getdate, today

from cgm_shipping.cgm_worldwide_shipping.customizations.license_reminders import (
	FIXED_EXPIRY,
	compute_status,
	get_due_reminder_for_license,
	get_recipients,
	get_reminder_periods,
	parse_email_list,
	reminder_already_sent,
)


class LicenseRegister(Document):
	def validate(self):
		self.validate_dates()
		self.validate_reminder_periods()
		self.validate_additional_recipients()
		self.set_status()

	def validate_dates(self):
		if self.issue_date and self.expiry_date and getdate(self.expiry_date) < getdate(self.issue_date):
			frappe.throw(
				_("Expiry Date cannot be before Issue Date."),
				title=_("Invalid Dates"),
			)

	def validate_reminder_periods(self):
		if not self.override_reminder_periods:
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

	def validate_additional_recipients(self):
		if not self.additional_recipients:
			return

		raw = [
			part.strip()
			for part in self.additional_recipients.replace("\n", ",").replace(";", ",").split(",")
			if part.strip()
		]
		valid = parse_email_list(self.additional_recipients)
		invalid = [email for email in raw if email not in valid]
		if invalid:
			frappe.throw(
				_("Not a valid email address: {0}").format(", ".join(invalid)),
				title=_("Invalid Recipient"),
			)

	def set_status(self):
		days_left = (
			date_diff(self.expiry_date, getdate(today()))
			if self.expiry_date and self.renewal_basis == FIXED_EXPIRY
			else None
		)
		self.status = compute_status(self, days_left)
		self.days_to_expiry = cint(days_left) if days_left is not None else 0


@frappe.whitelist()
def get_reminder_schedule(license_name):
	"""Explain, for one licence, when the next reminder goes out and who receives it.

	Backs the "Reminder Schedule" button on the licence form so the schedule is visible
	without waiting for the daily job to run.
	"""
	licence = frappe.get_doc("License Register", license_name)
	licence.check_permission("read")

	settings = frappe.get_cached_doc("License Settings")
	user_emails, extra_emails = get_recipients(licence, settings)
	due_today = get_due_reminder_for_license(licence, settings)

	return {
		"enabled": bool(settings.enable_notifications),
		"recipients": sorted(set(user_emails) | set(extra_emails)),
		"due_today": bool(due_today),
		"due_label": due_today["label"] if due_today else None,
		"schedule": build_schedule(licence, settings),
	}


def build_schedule(licence, settings):
	if licence.renewal_basis != FIXED_EXPIRY or not licence.expiry_date:
		return []

	schedule = []
	for period in sorted(
		get_reminder_periods(licence, settings), key=lambda p: cint(p.days_before), reverse=True
	):
		days_before = cint(period.days_before)
		send_on = add_days(getdate(licence.expiry_date), -days_before)
		schedule.append(
			{
				"days_before": days_before,
				"label": period.label or _("{0} days before expiry").format(days_before),
				"send_on": format_date(send_on),
				"sent": reminder_already_sent(
					licence.name, "Upcoming", licence.expiry_date, days_before
				),
				"past": getdate(send_on) < getdate(today()),
			}
		)

	return schedule
