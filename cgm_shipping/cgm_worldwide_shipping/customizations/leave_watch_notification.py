"""Tell the leave watcher who is going away, so departments can be warned.

Quality assurance used to hear about every leave application because she happened
to hold Senior Operations Manager and Director. Those are approval rights, not a
mailing list, and when the role profiles were reorganised on 30 October she lost
both and the emails stopped. Putting the roles back would have handed her the power
to approve leave in order to fix an email, so these are notices of their own.

Two of them, at the two moments worth telling somebody about:

* **Applied** - so and so has asked for leave, these dates. Warn the department.
* **Line manager approved** - it has cleared the first approval and is likely to
  happen, so the cover can be arranged.

The later steps each have their own notification aimed at whoever must act, and the
watcher acts on none of them, so they are not copied in.

Who is told is a list in CGM Shipping Settings > Leave Watchers, not a role. A role
is held by whoever the role profiles say, which is far more people than should get
this, and it changes under you - which is exactly how these notices went missing.

Both stand down on the watcher's own leave: they already get the ordinary employee
notification, and being told they have applied for their own leave is noise.

Seeded on migrate and never rewritten, so wording and recipients can be tuned in
Desk without a deploy putting them back.
"""

from __future__ import annotations

import frappe

LEAVE_APPLICATION = "Leave Application"
SETTINGS = "CGM Shipping Settings"

#: Who is told, named in CGM Shipping Settings > Leave Watchers. A list of people
#: rather than a role: a role is held by whoever the role profiles say, which is far
#: more people than should get this, and it changes under you - that is exactly how
#: these notices went missing in the first place. Remove someone from the list and
#: their notices stop.
WATCHERS_FIELD = "custom_leave_watchers"

#: Stamped on the application so the Notification can address it. A Notification
#: cannot read a Settings table, but it can read a field on the document.
EMAILS_FIELD = "custom_leave_watcher_emails"

LINE_MANAGER_STATE = "Pending Line Manager Approval"

#: Where an application lands once the line manager approves it. Which one depends
#: on the employee's route, so all three count as "the line manager has approved".
AFTER_LINE_MANAGER = (
	"Pending Senior Supervisor Approval",
	"Pending Operations Manager Approval",
	"Pending HR Approval",
)


def _message(label: str, headline: str, intro: str) -> str:
	return f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
            max-width:620px;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">
  <div style="height:5px;background:#15803d;"></div>
  <div style="padding:26px 30px 30px;">
    <div style="color:#15803d;font-size:12px;font-weight:700;letter-spacing:.09em;">{label}</div>
    <h2 style="margin:10px 0 6px;font-size:22px;line-height:1.3;color:#111827;font-weight:700;">
      {headline}
    </h2>
    <p style="margin:0 0 22px;color:#4b5563;font-size:15px;line-height:1.5;">{intro}</p>
    <table style="width:100%;border-collapse:collapse;font-size:15px;">
      <tr><td style="padding:11px 0;color:#6b7280;border-bottom:1px solid #f3f4f6;">Employee</td>
          <td style="padding:11px 0;text-align:right;font-weight:700;color:#111827;
                     border-bottom:1px solid #f3f4f6;">
            {{{{ doc.employee_name }}}} &middot; {{{{ doc.employee }}}}</td></tr>
      {{% if doc.department %}}
      <tr><td style="padding:11px 0;color:#6b7280;border-bottom:1px solid #f3f4f6;">Department</td>
          <td style="padding:11px 0;text-align:right;font-weight:700;color:#111827;
                     border-bottom:1px solid #f3f4f6;">{{{{ doc.department }}}}</td></tr>
      {{% endif %}}
      <tr><td style="padding:11px 0;color:#6b7280;border-bottom:1px solid #f3f4f6;">Leave type</td>
          <td style="padding:11px 0;text-align:right;font-weight:700;color:#111827;
                     border-bottom:1px solid #f3f4f6;">{{{{ doc.leave_type }}}}</td></tr>
      <tr><td style="padding:11px 0;color:#6b7280;border-bottom:1px solid #f3f4f6;">Dates</td>
          <td style="padding:11px 0;text-align:right;font-weight:700;color:#111827;
                     border-bottom:1px solid #f3f4f6;">
            {{{{ frappe.utils.formatdate(doc.from_date) }}}}
            &ndash; {{{{ frappe.utils.formatdate(doc.to_date) }}}}</td></tr>
      <tr><td style="padding:11px 0;color:#6b7280;border-bottom:1px solid #f3f4f6;">Days</td>
          <td style="padding:11px 0;text-align:right;font-weight:700;color:#111827;
                     border-bottom:1px solid #f3f4f6;">{{{{ doc.total_leave_days }}}}</td></tr>
      <tr><td style="padding:11px 0;color:#6b7280;">Line manager</td>
          <td style="padding:11px 0;text-align:right;font-weight:700;color:#111827;">
            {{{{ doc.leave_approver_name or "-" }}}}</td></tr>
    </table>
    <div style="margin-top:26px;">
      <a href="{{{{ frappe.utils.get_url_to_form(doc.doctype, doc.name) }}}}"
         style="display:inline-block;background:#15803d;color:#ffffff;text-decoration:none;
                padding:13px 26px;border-radius:7px;font-weight:700;font-size:15px;">
        Open the application
      </a>
    </div>
    <p style="margin:24px 0 0;color:#9ca3af;font-size:13px;">
      You are told because you hold the leave watch role. No action is needed from you.
    </p>
  </div>
</div>
"""


_AFTER = ", ".join(f'"{state}"' for state in AFTER_LINE_MANAGER)

#: name -> how it fires and what it says.
WATCH_NOTIFICATIONS = {
	"CGM Leave - Watch (Applied)": {
		"subject": "Leave applied - {{ doc.employee_name }}, {{ doc.leave_type }}",
		"event": "New",
		"condition": f'doc.workflow_state == "{LINE_MANAGER_STATE}"',
		"value_changed": None,
		"message": _message(
			"LEAVE APPLIED",
			"{{ doc.employee_name }} has applied for leave",
			"It is with {{ doc.leave_approver_name or 'the line manager' }} for the first "
			"approval. Let the department know they may be away.",
		),
	},
	"CGM Leave - Watch (Line Manager Approved)": {
		"subject": "Leave approved by line manager - {{ doc.employee_name }}",
		"event": "Value Change",
		"condition": f"doc.workflow_state in ({_AFTER})",
		"value_changed": "workflow_state",
		"message": _message(
			"LINE MANAGER APPROVED",
			"{{ doc.employee_name }}'s leave has cleared the line manager",
			"{{ doc.leave_approver_name or 'The line manager' }} has approved it. It is "
			"likely to go ahead, so cover can be arranged.",
		),
	},
}


def leave_watchers() -> list[str]:
	"""The enabled users named in Settings > Leave Watchers."""
	try:
		settings = frappe.get_cached_doc(SETTINGS)
	except Exception:
		return []
	if not settings.meta.has_field(WATCHERS_FIELD):
		return []
	users = []
	for row in settings.get(WATCHERS_FIELD) or []:
		user = (row.get("user") or "").strip()
		if user and user not in users:
			users.append(user)
	if not users:
		return []
	# A disabled login is somebody who has left. Still listed, no longer written to.
	return [
		u.name
		for u in frappe.get_all(
			"User",
			filters={"name": ["in", users], "enabled": 1},
			fields=["name"],
		)
	]


def watcher_emails_for(doc) -> str:
	"""Who to tell about this application, as the Notification wants it.

	The applicant is left out of their own: they already get the ordinary employee
	notification, and being told they have applied for their own leave is noise.
	"""
	applicant = (doc.get("custom_employee_user") or "").strip().lower()
	emails = []
	for user in leave_watchers():
		if user.strip().lower() == applicant:
			continue
		email = frappe.db.get_value("User", user, "email") or user
		if email and email not in emails:
			emails.append(email)
	return ", ".join(emails)


def set_leave_watcher_emails(doc, method=None) -> None:
	"""Stamp the recipients on validate, before any workflow action."""
	if not doc.meta.has_field(EMAILS_FIELD):
		return
	wanted = watcher_emails_for(doc)
	if (doc.get(EMAILS_FIELD) or "") != wanted:
		doc.set(EMAILS_FIELD, wanted)


def ensure_leave_watch_notifications() -> int:
	"""Create the watch notifications once. Never rewrite one that exists.

	Ops tune wording and recipients in Desk; a migrate that put them back would undo
	that silently. Returns how many were created.
	"""
	if not frappe.db.exists("DocType", "Notification"):
		return 0

	created = 0
	for name, spec in WATCH_NOTIFICATIONS.items():
		if frappe.db.exists("Notification", name):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Notification",
				"name": name,
				"subject": spec["subject"],
				"document_type": LEAVE_APPLICATION,
				"channel": "Email",
				"event": spec["event"],
				"value_changed": spec["value_changed"],
				"enabled": 1,
				"is_standard": 0,
				"send_system_notification": 1,
				"condition": spec["condition"],
				"message": spec["message"],
				# Addressed from the field stamped on validate, so Settings decides
				# who hears about this and the applicant is already left out.
				"recipients": [{"receiver_by_document_field": EMAILS_FIELD}],
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		created += 1
	return created
