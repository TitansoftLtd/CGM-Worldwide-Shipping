# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

"""Expiry reminders for the licence & permit register.

The daily scheduler calls :func:`send_license_expiry_reminders`. It refreshes every
licence's status, works out which reminders are due today, and sends them by email
and/or in-app notification. Every send is written to a License Reminder Log, which is
also what stops the same reminder going out twice.
"""

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.utils import (
	cint,
	date_diff,
	format_date,
	get_datetime,
	get_url_to_form,
	getdate,
	now_datetime,
	today,
	validate_email_address,
)

FIXED_EXPIRY = "Fixed Expiry Date"
ONGOING = "Ongoing / No Expiry"
RENEW_WHEN_NEEDED = "Renew When Needed"


# ---------------------------------------------------------------------------
# Scheduler entry point
# ---------------------------------------------------------------------------


def send_license_expiry_reminders():
	"""Daily scheduler job: refresh statuses, then send whatever is due today."""
	refresh_license_statuses()

	settings = frappe.get_cached_doc("License Settings")
	if not settings.enable_notifications:
		return

	if not (settings.notify_by_email or settings.notify_in_app):
		return

	for reminder in get_due_reminders(settings):
		try:
			send_reminder(reminder, settings)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title=f"Licence reminder failed: {reminder['license'].name}",
				message=frappe.get_traceback(with_context=True),
			)


def refresh_license_statuses():
	"""Recompute ``status`` and ``days_to_expiry`` for every licence.

	Written with ``db.set_value`` rather than ``doc.save`` so the daily run does not
	churn the modified timestamp or create a version row for every licence.
	"""
	warning_window = get_warning_window()
	today_date = getdate(today())

	for row in frappe.get_all(
		"License Register",
		fields=["name", "status", "days_to_expiry", "expiry_date", "renewal_basis", "disabled"],
	):
		days_left = date_diff(row.expiry_date, today_date) if row.expiry_date else None
		status = compute_status(row, days_left, warning_window)
		expected_days = days_left if row.renewal_basis == FIXED_EXPIRY else 0

		if row.status == status and cint(row.days_to_expiry) == cint(expected_days):
			continue

		frappe.db.set_value(
			"License Register",
			row.name,
			{"status": status, "days_to_expiry": cint(expected_days)},
			update_modified=False,
		)

	frappe.db.commit()


def compute_status(license_row, days_left, warning_window=None):
	"""Derive the status shown on the licence. ``license_row`` may be a doc or a dict."""
	if cint(license_row.get("disabled")):
		return "Disabled"

	basis = license_row.get("renewal_basis")
	if basis == ONGOING:
		return "Ongoing"
	if basis == RENEW_WHEN_NEEDED:
		return "Renewal Required"

	if days_left is None:
		return "Renewal Required"
	if days_left < 0:
		return "Expired"

	if warning_window is None:
		warning_window = get_warning_window()
	if days_left <= warning_window:
		return "Expiring Soon"

	return "Active"


def get_warning_window():
	"""Days before expiry at which a licence starts showing as "Expiring Soon".

	This is the widest configured notification period, so the status flips to a warning
	on the same day the first reminder goes out. With no periods configured there is no
	warning window, and a licence stays Active right up until it expires.
	"""
	settings = frappe.get_cached_doc("License Settings")
	periods = [cint(row.days_before) for row in settings.reminder_periods if cint(row.days_before) > 0]
	return max(periods) if periods else 0


# ---------------------------------------------------------------------------
# Working out what is due
# ---------------------------------------------------------------------------


def get_due_reminders(settings=None):
	"""Return the reminders that should go out today.

	Each entry is a dict with the licence doc, the reminder type, the day count and a
	human label. Nothing is sent or logged here, so this is also what powers the
	"Preview Today's Reminders" button in License Settings.
	"""
	settings = settings or frappe.get_cached_doc("License Settings")
	due = []

	names = frappe.get_all("License Register", filters={"disabled": 0}, pluck="name")
	for name in names:
		license_doc = frappe.get_doc("License Register", name)
		reminder = get_due_reminder_for_license(license_doc, settings)
		if reminder:
			due.append(reminder)

	due.sort(key=lambda r: (r["reminder_type"] != "Overdue", r["days"]))
	return due


def get_due_reminder_for_license(license_doc, settings):
	if cint(license_doc.disabled):
		return None

	if license_doc.renewal_basis == ONGOING:
		return None

	if license_doc.renewal_basis == RENEW_WHEN_NEEDED:
		return get_due_review_reminder(license_doc, settings)

	if not license_doc.expiry_date:
		return get_due_review_reminder(license_doc, settings)

	days_left = date_diff(license_doc.expiry_date, getdate(today()))
	if days_left < 0:
		return get_due_overdue_reminder(license_doc, settings, days_left)

	return get_due_upcoming_reminder(license_doc, settings, days_left)


def get_due_upcoming_reminder(license_doc, settings, days_left):
	"""Fire the tightest notification period the licence has crossed into.

	With periods of 90/60/30/14/7 and 45 days to go, the licence sits in the 60-day
	band, so the 60-day reminder is the one that goes out. Each band fires once per
	expiry date, so a licence added when it is already close to expiry gets a single
	reminder rather than one for every band it skipped past.
	"""
	periods = get_reminder_periods(license_doc, settings)
	candidates = [p for p in periods if cint(p.days_before) >= days_left]
	if not candidates:
		return None

	period = min(candidates, key=lambda p: cint(p.days_before))
	days_before = cint(period.days_before)

	if reminder_already_sent(license_doc.name, "Upcoming", license_doc.expiry_date, days_before):
		return None

	return {
		"license": license_doc,
		"reminder_type": "Upcoming",
		"days": days_left,
		"days_before": days_before,
		"label": period.label or _("{0} days before expiry").format(days_before),
	}


def get_due_overdue_reminder(license_doc, settings, days_left):
	if not settings.notify_after_expiry:
		return None

	days_overdue = abs(days_left)
	stop_after = cint(settings.stop_expired_reminders_after)
	if stop_after and days_overdue > stop_after:
		return None

	frequency = cint(settings.expired_reminder_frequency)
	if not frequency:
		return None

	last_sent = get_last_reminder_datetime(license_doc.name, "Overdue", license_doc.expiry_date)
	if last_sent and date_diff(today(), last_sent.date()) < frequency:
		return None

	return {
		"license": license_doc,
		"reminder_type": "Overdue",
		"days": days_left,
		"days_before": days_left,
		"label": _("Expired {0} days ago").format(days_overdue),
	}


def get_due_review_reminder(license_doc, settings):
	"""Periodic nudge for licences with no fixed expiry date to work from."""
	if not settings.notify_renewal_required:
		return None

	frequency = cint(settings.renewal_required_frequency)
	if not frequency:
		return None

	last_sent = get_last_reminder_datetime(license_doc.name, "Review", None)
	if last_sent and date_diff(today(), last_sent.date()) < frequency:
		return None

	return {
		"license": license_doc,
		"reminder_type": "Review",
		"days": 0,
		"days_before": 0,
		"label": _("Due for review"),
	}


def get_reminder_periods(license_doc, settings):
	"""Per-licence overrides win; otherwise the defaults from License Settings."""
	if cint(license_doc.get("override_reminder_periods")) and license_doc.get("reminder_periods"):
		periods = license_doc.reminder_periods
	else:
		periods = settings.reminder_periods

	return [p for p in periods if cint(p.days_before) >= 0]


def reminder_already_sent(license_name, reminder_type, expiry_date, days_before):
	return bool(
		frappe.db.exists(
			"License Reminder Log",
			{
				"license": license_name,
				"reminder_type": reminder_type,
				"expiry_date": expiry_date,
				"reminder_days": cint(days_before),
				"status": "Sent",
			},
		)
	)


def get_last_reminder_datetime(license_name, reminder_type, expiry_date):
	filters = {"license": license_name, "reminder_type": reminder_type, "status": "Sent"}
	if expiry_date:
		filters["expiry_date"] = expiry_date

	last = frappe.get_all(
		"License Reminder Log",
		filters=filters,
		fields=["sent_on"],
		order_by="sent_on desc",
		limit=1,
	)
	return get_datetime(last[0].sent_on) if last and last[0].sent_on else None


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


def send_reminder(reminder, settings=None):
	settings = settings or frappe.get_cached_doc("License Settings")
	license_doc = reminder["license"]

	user_emails, extra_emails = get_recipients(license_doc, settings)
	all_emails = sorted(set(user_emails) | set(extra_emails))
	if not all_emails:
		return

	subject = build_subject(reminder)
	channels = []
	errors = []

	if settings.notify_in_app and user_emails:
		try:
			enqueue_create_notification(
				user_emails,
				{
					"type": "Alert",
					"subject": subject,
					"email_content": build_notification_content(reminder),
					"document_type": "License Register",
					"document_name": license_doc.name,
				},
			)
			channels.append("In-App")
		except Exception as exception:
			errors.append(f"In-App: {exception}")

	if settings.notify_by_email:
		try:
			frappe.sendmail(
				recipients=all_emails,
				subject=subject,
				message=build_email_body(reminder),
				reference_doctype="License Register",
				reference_name=license_doc.name,
			)
			channels.append("Email")
		except Exception as exception:
			errors.append(f"Email: {exception}")

	error = "; ".join(errors) or None

	if not channels:
		log_reminder(reminder, all_emails, [], status="Failed", error=error)
		return

	log_reminder(reminder, all_emails, channels, error=error)
	frappe.db.set_value(
		"License Register",
		license_doc.name,
		{"last_reminder_sent_on": now_datetime()},
		update_modified=False,
	)


def get_recipients(license_doc, settings):
	"""Return ``(user_emails, extra_emails)``.

	Only the first list can receive in-app notifications - the second is made up of
	plain addresses that have no user account behind them.
	"""
	user_names = {row.user for row in settings.notify_users if row.user}

	roles = [row.role for row in settings.notify_roles if row.role]
	if roles:
		user_names.update(
			frappe.get_all(
				"Has Role",
				filters={"role": ["in", roles], "parenttype": "User"},
				pluck="parent",
			)
		)

	if settings.notify_responsible_person and license_doc.responsible_person:
		user_names.add(license_doc.responsible_person)

	user_names.discard("Guest")

	user_emails = []
	if user_names:
		user_emails = [
			user.email or user.name
			for user in frappe.get_all(
				"User",
				filters={"name": ["in", list(user_names)], "enabled": 1},
				fields=["name", "email"],
			)
			if user.email or "@" in user.name
		]

	extra_emails = parse_email_list(settings.additional_emails) + parse_email_list(
		license_doc.additional_recipients
	)
	extra_emails = [email for email in extra_emails if email not in user_emails]

	return sorted(set(user_emails)), sorted(set(extra_emails))


def parse_email_list(value):
	if not value:
		return []

	candidates = [part.strip() for part in value.replace("\n", ",").replace(";", ",").split(",")]
	return [email for email in candidates if email and validate_email_address(email)]


def build_subject(reminder):
	license_doc = reminder["license"]
	name = license_doc.license_name

	if reminder["reminder_type"] == "Overdue":
		return _("OVERDUE: {0} expired {1} days ago").format(name, abs(cint(reminder["days"])))

	if reminder["reminder_type"] == "Review":
		return _("Licence due for review: {0}").format(name)

	days = cint(reminder["days"])
	if days == 0:
		return _("Licence expires today: {0}").format(name)
	if days == 1:
		return _("Licence expires tomorrow: {0}").format(name)

	return _("Licence expires in {0} days: {1}").format(days, name)


def build_notification_content(reminder):
	license_doc = reminder["license"]
	parts = [license_doc.license_type]

	if license_doc.expiry_date:
		parts.append(_("Expiry: {0}").format(format_date(license_doc.expiry_date)))
	if license_doc.service_provider:
		parts.append(license_doc.service_provider)

	return " &middot; ".join(frappe.utils.escape_html(part) for part in parts if part)


def build_email_body(reminder):
	license_doc = reminder["license"]
	rows = [
		(_("Licence / Permit"), license_doc.license_name),
		(_("Type"), license_doc.license_type),
		(_("Licence No"), license_doc.license_number),
		(_("Company"), license_doc.company),
		(_("Expiry Date"), format_date(license_doc.expiry_date) if license_doc.expiry_date else None),
		(_("Service Provider"), license_doc.service_provider),
		(_("Contact Person"), license_doc.contact_person),
		(_("Telephone"), license_doc.phone),
		(_("Email"), license_doc.email),
	]

	table_rows = "".join(
		f"<tr>"
		f'<td style="padding:4px 12px 4px 0;color:#6c7680;white-space:nowrap;">{frappe.utils.escape_html(label)}</td>'
		f'<td style="padding:4px 0;"><b>{frappe.utils.escape_html(str(value))}</b></td>'
		f"</tr>"
		for label, value in rows
		if value
	)

	if reminder["reminder_type"] == "Overdue":
		lead = _("This licence expired {0} days ago and is still marked as not renewed.").format(
			abs(cint(reminder["days"]))
		)
	elif reminder["reminder_type"] == "Review":
		lead = _(
			"This licence has no fixed expiry date and is due for a review - confirm whether it needs renewing."
		)
	else:
		lead = _("This licence is due to expire in {0} days ({1}).").format(
			cint(reminder["days"]), reminder["label"]
		)

	link = get_url_to_form("License Register", license_doc.name)

	return f"""
		<p>{frappe.utils.escape_html(lead)}</p>
		<table style="border-collapse:collapse;font-size:13px;margin:16px 0;">{table_rows}</table>
		<p><a href="{link}" style="background:#171717;color:#fff;padding:8px 14px;border-radius:6px;text-decoration:none;">{_("Open Licence")}</a></p>
		<p style="color:#8d959e;font-size:12px;margin-top:20px;">
			{_("Sent by the licence register. Reminder schedule and recipients are configured under License Settings.")}
		</p>
	"""


def log_reminder(reminder, recipients, channels, status="Sent", error=None):
	license_doc = reminder["license"]

	log = frappe.new_doc("License Reminder Log")
	log.update(
		{
			"license": license_doc.name,
			"reminder_type": reminder["reminder_type"],
			"reminder_days": cint(reminder["days_before"]),
			"expiry_date": license_doc.expiry_date,
			"sent_on": now_datetime(),
			"status": status,
			"channels": ", ".join(channels),
			"recipients": ", ".join(recipients),
			"error": error,
		}
	)
	log.insert(ignore_permissions=True)
	return log


# ---------------------------------------------------------------------------
# Buttons on License Settings
# ---------------------------------------------------------------------------


@frappe.whitelist()
def preview_due_reminders():
	"""Dry run: what would go out today, and to whom. Sends nothing, logs nothing."""
	frappe.only_for(["System Manager", "License Manager"])

	settings = frappe.get_cached_doc("License Settings")
	preview = []

	for reminder in get_due_reminders(settings):
		user_emails, extra_emails = get_recipients(reminder["license"], settings)
		preview.append(
			{
				"license": reminder["license"].name,
				"license_name": reminder["license"].license_name,
				"expiry_date": reminder["license"].expiry_date,
				"reminder_type": reminder["reminder_type"],
				"days": cint(reminder["days"]),
				"label": reminder["label"],
				"recipients": sorted(set(user_emails) | set(extra_emails)),
			}
		)

	return {"enabled": bool(settings.enable_notifications), "reminders": preview}


@frappe.whitelist()
def run_reminders_now():
	"""Run the daily check immediately, for real."""
	frappe.only_for(["System Manager", "License Manager"])

	before = frappe.db.count("License Reminder Log")
	send_license_expiry_reminders()
	return {"sent": frappe.db.count("License Reminder Log") - before}
