# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import unittest

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from cgm_shipping.cgm_worldwide_shipping.customizations.license_reminders import (
	get_due_reminder_for_license,
	get_recipients,
	log_reminder,
)

# These tests build every record they need, so skip Frappe's generated test records -
# the User ones in particular trip over a site's password policy.
IGNORE_TEST_RECORD_DEPENDENCIES = ["User", "Company", "License Type", "Licensing Contact"]

TEST_LICENSE_TYPE = "_Test Licence Type"

# The app seeds a default schedule on fresh installs only, so the tests pin the
# settings they depend on rather than reading whatever is configured on the site.
TEST_REMINDER_PERIODS = [(90, "3 months out"), (60, "2 months out"), (30, "1 month out"), (14, "2 weeks out"), (7, "Final week")]
TEST_EXPIRED_FREQUENCY = 7
TEST_STOP_AFTER = 180
TEST_REVIEW_FREQUENCY = 30


class TestLicenseRegister(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.company = frappe.db.get_value("Company", {}, "name")
		if not cls.company:
			raise unittest.SkipTest("No Company on this site to attach test licences to.")

		if not frappe.db.exists("License Type", TEST_LICENSE_TYPE):
			frappe.get_doc({"doctype": "License Type", "type_name": TEST_LICENSE_TYPE}).insert(
				ignore_permissions=True
			)

		cls.settings = frappe.get_single("License Settings")
		cls.settings.enable_notifications = 1
		cls.settings.notify_after_expiry = 1
		cls.settings.expired_reminder_frequency = TEST_EXPIRED_FREQUENCY
		cls.settings.stop_expired_reminders_after = TEST_STOP_AFTER
		cls.settings.notify_renewal_required = 1
		cls.settings.renewal_required_frequency = TEST_REVIEW_FREQUENCY
		cls.settings.reminder_periods = []
		for days, label in TEST_REMINDER_PERIODS:
			cls.settings.append(
				"reminder_periods", {"days_before": days, "label": label}
			)

		# Saved, not just held in memory: compute_status() reads the widest period back
		# through the document cache. The class-level rollback undoes this afterwards.
		cls.settings.flags.ignore_permissions = True
		cls.settings.save()
		frappe.clear_cache(doctype="License Settings")

	def make_license(self, **kwargs):
		values = {
			"doctype": "License Register",
			"license_name": f"_Test Licence {frappe.generate_hash(length=8)}",
			"license_type": TEST_LICENSE_TYPE,
			"company": self.company,
			"renewal_basis": "Fixed Expiry Date",
			"expiry_date": add_days(today(), 45),
		}
		values.update(kwargs)
		return frappe.get_doc(values).insert()

	# -- status ------------------------------------------------------------

	def test_status_follows_expiry_date(self):
		self.assertEqual(self.make_license(expiry_date=add_days(today(), 500)).status, "Active")
		self.assertEqual(self.make_license(expiry_date=add_days(today(), 10)).status, "Expiring Soon")
		self.assertEqual(self.make_license(expiry_date=add_days(today(), -1)).status, "Expired")
		self.assertEqual(self.make_license(expiry_date=today()).status, "Expiring Soon")

	def test_status_for_undated_renewal_bases(self):
		self.assertEqual(self.make_license(renewal_basis="Ongoing / No Expiry").status, "Ongoing")
		self.assertEqual(
			self.make_license(renewal_basis="Renew When Needed").status, "Renewal Required"
		)

	def test_disabled_licence_overrides_status(self):
		licence = self.make_license(expiry_date=add_days(today(), -30), disabled=1)
		self.assertEqual(licence.status, "Disabled")
		self.assertIsNone(get_due_reminder_for_license(licence, self.settings))

	def test_days_to_expiry_is_negative_when_overdue(self):
		self.assertEqual(self.make_license(expiry_date=add_days(today(), -12)).days_to_expiry, -12)

	# -- validation --------------------------------------------------------

	def test_expiry_before_issue_date_is_rejected(self):
		self.assertRaises(
			frappe.ValidationError,
			self.make_license,
			issue_date=today(),
			expiry_date=add_days(today(), -1),
		)

	def test_duplicate_reminder_period_is_rejected(self):
		self.assertRaises(
			frappe.ValidationError,
			self.make_license,
			override_reminder_periods=1,
			reminder_periods=[{"days_before": 30}, {"days_before": 30}],
		)

	def test_invalid_additional_recipient_is_rejected(self):
		self.assertRaises(
			frappe.ValidationError, self.make_license, additional_recipients="nope, a@b.com"
		)

	# -- which reminder is due --------------------------------------------

	def test_tightest_band_wins(self):
		"""45 days out sits in the 60-day band, not the 90-day one."""
		licence = self.make_license(expiry_date=add_days(today(), 45))
		reminder = get_due_reminder_for_license(licence, self.settings)
		self.assertEqual(reminder["reminder_type"], "Upcoming")
		self.assertEqual(reminder["days_before"], 60)
		self.assertEqual(reminder["days"], 45)

	def test_nothing_due_beyond_the_widest_band(self):
		licence = self.make_license(expiry_date=add_days(today(), 200))
		self.assertIsNone(get_due_reminder_for_license(licence, self.settings))

	def test_band_fires_only_once_per_expiry_date(self):
		licence = self.make_license(expiry_date=add_days(today(), 45))
		reminder = get_due_reminder_for_license(licence, self.settings)
		log_reminder(reminder, ["someone@example.com"], ["Email"])

		self.assertIsNone(get_due_reminder_for_license(licence, self.settings))

	def test_renewal_resets_the_schedule(self):
		licence = self.make_license(expiry_date=add_days(today(), 45))
		log_reminder(
			get_due_reminder_for_license(licence, self.settings), ["someone@example.com"], ["Email"]
		)

		# Renewed well into the future - nothing is due any more.
		licence.expiry_date = add_days(today(), 400)
		licence.save()
		self.assertIsNone(get_due_reminder_for_license(licence, self.settings))

		# A new expiry date is a new schedule, so the bands fire again.
		licence.expiry_date = add_days(today(), 55)
		licence.save()
		reminder = get_due_reminder_for_license(licence, self.settings)
		self.assertIsNotNone(reminder)
		self.assertEqual(reminder["days_before"], 60)

	def test_restoring_the_same_expiry_date_does_not_resend(self):
		"""Correcting a mistyped date back to what it was must not re-spam recipients."""
		licence = self.make_license(expiry_date=add_days(today(), 45))
		log_reminder(
			get_due_reminder_for_license(licence, self.settings), ["someone@example.com"], ["Email"]
		)

		licence.expiry_date = add_days(today(), 400)
		licence.save()
		licence.expiry_date = add_days(today(), 45)
		licence.save()

		self.assertIsNone(get_due_reminder_for_license(licence, self.settings))

	def test_expired_licence_repeats_on_a_frequency(self):
		licence = self.make_license(expiry_date=add_days(today(), -5))

		reminder = get_due_reminder_for_license(licence, self.settings)
		self.assertEqual(reminder["reminder_type"], "Overdue")
		self.assertEqual(reminder["days"], -5)

		log = log_reminder(reminder, ["someone@example.com"], ["Email"])
		self.assertIsNone(get_due_reminder_for_license(licence, self.settings))

		# Backdate the log past the repeat interval and it becomes due again.
		frappe.db.set_value(
			"License Reminder Log",
			log.name,
			"sent_on",
			add_days(today(), -(self.settings.expired_reminder_frequency + 1)),
		)
		self.assertIsNotNone(get_due_reminder_for_license(licence, self.settings))

	def test_expired_reminders_stop_after_the_cutoff(self):
		overdue_by = (self.settings.stop_expired_reminders_after or 180) + 1
		licence = self.make_license(expiry_date=add_days(today(), -overdue_by))
		self.assertIsNone(get_due_reminder_for_license(licence, self.settings))

	def test_ongoing_licence_never_reminds(self):
		licence = self.make_license(renewal_basis="Ongoing / No Expiry", expiry_date=None)
		self.assertIsNone(get_due_reminder_for_license(licence, self.settings))

	def test_renew_when_needed_gets_a_review_reminder(self):
		licence = self.make_license(renewal_basis="Renew When Needed", expiry_date=None)
		reminder = get_due_reminder_for_license(licence, self.settings)
		self.assertEqual(reminder["reminder_type"], "Review")

		log_reminder(reminder, ["someone@example.com"], ["Email"])
		self.assertIsNone(get_due_reminder_for_license(licence, self.settings))

	def test_per_licence_override_beats_the_defaults(self):
		licence = self.make_license(
			expiry_date=add_days(today(), 45),
			override_reminder_periods=1,
			reminder_periods=[{"days_before": 50, "label": "Custom"}],
		)
		reminder = get_due_reminder_for_license(licence, self.settings)
		self.assertEqual(reminder["days_before"], 50)
		self.assertEqual(reminder["label"], "Custom")

	# -- recipients --------------------------------------------------------

	def test_recipients_drop_invalid_addresses(self):
		licence = self.make_license(additional_recipients="valid@example.com")
		settings = frappe.get_single("License Settings")
		settings.additional_emails = "another@example.com"

		_, extra = get_recipients(licence, settings)
		self.assertIn("valid@example.com", extra)
		self.assertIn("another@example.com", extra)

	def test_responsible_person_is_included_when_enabled(self):
		licence = self.make_license(responsible_person="Administrator")
		settings = frappe.get_single("License Settings")
		settings.notify_responsible_person = 1

		users, _ = get_recipients(licence, settings)
		self.assertIn(frappe.db.get_value("User", "Administrator", "email"), users)

		settings.notify_responsible_person = 0
		users, _ = get_recipients(licence, settings)
		self.assertNotIn(frappe.db.get_value("User", "Administrator", "email"), users)
