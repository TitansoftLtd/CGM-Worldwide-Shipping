"""Send to whoever is actually doing the work, not to everyone holding the role.

A notification row naming a role goes to every holder of that role. For a role of
twelve people that is twelve messages about one task, eleven of which are noise -
and because it is noise, the one person who needed it learns to ignore it.

Where somebody is assigned, they are the right recipient. CGM Shipping Settings
maps a role to where that assignment lives:

* **Field Operations Officers** - whoever is assigned to the task itself.
* **Declarant** - whoever is assigned to the shipment the task belongs to, since
  declaration work is owned per shipment rather than per task.

With nobody assigned the row falls back to the whole role, so a notification is
never silently dropped. Roles absent from the map are untouched: a row naming
Director still reaches every Director, which is what makes it safe to put a
narrowed role and a broad one on the same notification.

Why this is an override rather than configuration:

* `send_to_all_assignees` is a notification-level checkbox, so it cannot vary by
  row, and it is read **only on the email path** - half of CGM's notifications are
  SMS, which would have silently kept the old behaviour.
* `get_assignees()` reads ToDos for the document itself, so it cannot reach the
  assignee of a linked Project.
* A per-row `condition` can suppress a row but cannot redirect it.

Resolution happens per recipient row and feeds both channels from one place, so
email and SMS cannot drift apart.
"""

from __future__ import annotations

import frappe
from frappe.email.doctype.notification.notification import Notification

SETTINGS_FIELD = "notification_assignment_routes"


def assignment_routes() -> dict[str, dict]:
	"""The role map from CGM Shipping Settings, keyed by role."""
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return {}
	# A Single has no table of its own, so `frappe.db.has_column` raises here.
	if not frappe.get_meta("CGM Shipping Settings").has_field(SETTINGS_FIELD):
		return {}
	settings = frappe.get_cached_doc("CGM Shipping Settings")
	routes = {}
	for row in settings.get(SETTINGS_FIELD) or []:
		if row.role:
			routes[row.role] = {
				"assigned_on": row.assigned_on or "Task",
				"fall_back_to_role": bool(row.fall_back_to_role),
			}
	return routes


def _project_of(doc) -> str | None:
	"""The shipment a document belongs to, if it names one."""
	for fieldname in ("project", "custom_project"):
		value = doc.get(fieldname)
		if value:
			return value
	return doc.name if doc.doctype == "Project" else None


def assigned_users(doc, assigned_on: str) -> list[str]:
	"""Open assignments on the document, or on the shipment it belongs to.

	Only `Open` counts. Completing a task or finishing a shipment closes its
	assignments (see `assignment_lifecycle`), which is what stops a finished job
	from carrying on notifying the person who finished it.
	"""
	if assigned_on == "Project":
		reference_type, reference_name = "Project", _project_of(doc)
	else:
		reference_type, reference_name = doc.doctype, doc.name
	if not reference_name:
		return []
	return frappe.get_all(
		"ToDo",
		filters={
			"reference_type": reference_type,
			"reference_name": reference_name,
			"status": "Open",
		},
		pluck="allocated_to",
	)


def resolve_role_recipients(doc, role: str, routes: dict[str, dict]) -> list[str] | None:
	"""Users a role row should reach, or None to leave the row alone.

	None and an empty list mean different things: None is "this role is not routed,
	handle it the normal way", while [] is "routed, nobody assigned, and the rule
	says do not fall back".
	"""
	route = routes.get(role)
	if not route:
		return None
	users = [u for u in dict.fromkeys(assigned_users(doc, route["assigned_on"])) if u]
	if users:
		return users
	return None if route["fall_back_to_role"] else []


class CGMNotification(Notification):
	"""Notification that sends to the assignee where there is one."""

	def _routed_users(self, doc, recipient) -> list[str] | None:
		if not recipient.receiver_by_role:
			return None
		return resolve_role_recipients(doc, recipient.receiver_by_role, assignment_routes())

	def get_list_of_recipients(self, doc, context):
		"""Email. Swap a routed role for its assignees, leave everything else."""
		routes = assignment_routes()
		if not routes:
			return super().get_list_of_recipients(doc, context)

		swapped = {}
		for recipient in self.recipients:
			users = self._routed_users(doc, recipient)
			if users is None:
				continue
			swapped[recipient.name] = (recipient.receiver_by_role, users)
			recipient.receiver_by_role = None
		try:
			recipients, cc, bcc = super().get_list_of_recipients(doc, context)
		finally:
			for recipient in self.recipients:
				if recipient.name in swapped:
					recipient.receiver_by_role = swapped[recipient.name][0]

		for role, users in swapped.values():
			for user in users:
				email = frappe.db.get_value("User", user, "email") or user
				if email:
					recipients.append(email)
		return list(set(recipients)), cc, bcc

	def get_receiver_list(self, doc, context, field_on_user="mobile_no", recipient_extractor_func=None):
		"""SMS, and anything else reading users by a field on User.

		Frappe's own assignee support never reached this path, which is why SMS is
		handled here rather than left to `send_to_all_assignees`.
		"""
		routes = assignment_routes()
		if not routes:
			return super().get_receiver_list(doc, context, field_on_user, recipient_extractor_func)

		swapped = {}
		for recipient in self.recipients:
			users = self._routed_users(doc, recipient)
			if users is None:
				continue
			swapped[recipient.name] = (recipient.receiver_by_role, users)
			recipient.receiver_by_role = None
		try:
			receivers = super().get_receiver_list(doc, context, field_on_user, recipient_extractor_func)
		finally:
			for recipient in self.recipients:
				if recipient.name in swapped:
					recipient.receiver_by_role = swapped[recipient.name][0]

		for role, users in swapped.values():
			for user in users:
				value = frappe.db.get_value("User", user, field_on_user)
				if value:
					receivers.append(value)
		return list(set(receivers))
