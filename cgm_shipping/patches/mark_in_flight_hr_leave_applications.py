"""Mark leave applications that were already in flight when the HR route arrived.

Why: the workflow decides an HR approver's route by reading `custom_applicant_is_hr`,
and that field is computed when an application is saved. Every application raised before
this deploy therefore carries 0, because adding the column backfilled the default rather
than working the value out per row. An HR approver's leave already sitting at Pending
Line Manager Approval would then take the old route, back to the HR step, which is the
self-approval this was meant to end.

What: works the flag out for each application still in flight and corrects the ones that
are wrong. Submitted and cancelled applications are left alone: their route is already
run, so the flag would only be cosmetic, and rewriting a submitted document to change
cosmetics is not worth the risk.

Written with `db.set_value` rather than the ORM: this is one derived flag with no hooks
behind it, and a save would re-run leave validation on documents nobody is editing.

Idempotent. Retire per docs/guides/patches.md once staging and production Patch Log
show it.
"""

import frappe

FIELD = "custom_applicant_is_hr"


def execute() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.leave_hr_approval import (
		hr_approval_roles,
	)

	if not frappe.get_meta("Leave Application").has_field(FIELD):
		# The field syncs in the same deploy; if it is absent there is nothing to correct.
		return

	roles = hr_approval_roles()
	if not roles:
		return

	applications = frappe.get_all(
		"Leave Application",
		filters={"docstatus": 0},
		fields=["name", "employee", "custom_employee_user", FIELD],
	)

	corrected = []
	for application in applications:
		user = application.custom_employee_user or frappe.db.get_value(
			"Employee", application.employee, "user_id"
		)
		is_hr = bool(user and set(frappe.get_roles(user)) & roles)
		if is_hr == bool(application.get(FIELD)):
			continue

		frappe.db.set_value(
			"Leave Application", application.name, FIELD, int(is_hr), update_modified=False
		)
		corrected.append(application.name)

	if corrected:
		frappe.db.commit()
		frappe.log_error(
			title="CGM patch: in-flight HR leave marked",
			message=(
				"These leave applications were still in flight and are raised by an HR "
				"approver, so they now complete at the line manager:\n"
				+ "\n".join(f"- {name}" for name in corrected)
			),
		)
