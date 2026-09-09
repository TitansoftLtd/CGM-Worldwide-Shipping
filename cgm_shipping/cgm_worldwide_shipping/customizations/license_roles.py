# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

"""Roles and starting configuration for the licence & permit register.

The License Register, License Type, Licensing Contact and License Settings doctypes
name these roles in their permissions, so they have to exist for those permissions to
mean anything. Nothing else is created on migrate - licences, types and contacts are
all entered by hand.

The default reminder schedule is seeded on a fresh install only, so that removing a
period on a live site does not bring it back on the next migrate.
"""

import frappe

ROLES = [
	{"role_name": "License Manager", "desk_access": 1},
	{"role_name": "License User", "desk_access": 1},
]

DEFAULT_REMINDER_PERIODS = [
	(90, "3 months out"),
	(60, "2 months out"),
	(30, "1 month out"),
	(14, "2 weeks out"),
	(7, "Final week"),
]


def ensure_license_roles() -> None:
	"""Create the licence roles if they are missing. Safe to run more than once."""
	for role in ROLES:
		if frappe.db.exists("Role", role["role_name"]):
			continue

		frappe.get_doc({"doctype": "Role", **role}).insert(ignore_permissions=True)


def seed_license_settings() -> None:
	"""Give a fresh site a working reminder schedule. Never overwrites existing rows."""
	if not frappe.db.exists("DocType", "License Settings"):
		return

	settings = frappe.get_single("License Settings")
	if settings.reminder_periods:
		return

	for days, label in DEFAULT_REMINDER_PERIODS:
		settings.append("reminder_periods", {"days_before": days, "label": label})

	settings.flags.ignore_permissions = True
	settings.save()
