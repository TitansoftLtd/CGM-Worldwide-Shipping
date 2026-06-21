"""Client inspection notification and confirmation (sea import task sequence 7)."""
from __future__ import annotations

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import get_url, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import SEA_TASK_FLOW_KEY
from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
	display_ref_from_values,
)

INSPECTION_TASK_SEQ = 7
TRACK_ETA_TASK_SEQ = 8  # legacy; kept for existing projects only


def sea_import_task_sequence_no(template_index: int) -> int:
	"""Map template row index → custom_sequence_no (gap at 8 for removed track-ETA task)."""
	return template_index if template_index < TRACK_ETA_TASK_SEQ else template_index + 1


def _get_inspection_task(task_name: str):
	task = frappe.get_doc("Task", task_name)
	if task.custom_task_flow_key != SEA_TASK_FLOW_KEY:
		frappe.throw(_("This action is only available on sea import clearance tasks."))
	if int(task.custom_sequence_no or 0) != INSPECTION_TASK_SEQ:
		frappe.throw(_("This action is only available on the Client conducts inspection task."))
	if not task.project:
		frappe.throw(_("Link this task to a Project before notifying the client."))
	return task


def get_inspection_task_for_project(project_name: str) -> dict | None:
	if not project_name:
		return None
	return frappe.db.get_value(
		"Task",
		{
			"project": project_name,
			"custom_task_flow_key": SEA_TASK_FLOW_KEY,
			"custom_sequence_no": INSPECTION_TASK_SEQ,
		},
		[
			"name",
			"custom_client_notified_on",
			"custom_client_notified_by",
			"custom_inspection_confirmed_on",
			"custom_inspection_confirmed_by",
		],
		as_dict=True,
	)


def get_customer_notification_emails(customer: str) -> list[str]:
	"""Primary contact, customer email, and portal user addresses."""
	if not customer:
		return []

	emails: list[str] = []
	seen: set[str] = set()

	def _add(value: str | None) -> None:
		addr = (value or "").strip()
		if addr and addr not in seen:
			seen.add(addr)
			emails.append(addr)

	row = frappe.db.get_value(
		"Customer",
		customer,
		["email_id", "customer_primary_contact"],
		as_dict=True,
	)
	if row:
		_add(row.email_id)
		if row.customer_primary_contact:
			_add(frappe.db.get_value("Contact", row.customer_primary_contact, "email_id"))

	for pu in frappe.get_all(
		"Portal User",
		filters={"parent": customer, "parenttype": "Customer"},
		fields=["user"],
	):
		_add(pu.user)

	return emails


def _project_inspection_fields(project_name: str) -> dict:
	meta = frappe.get_meta("Project")
	fields = ["name", "customer"]
	for field in (
		"custom_inspection_notification_status",
		"custom_inspection_notified_on",
		"custom_inspection_confirmed_on",
		"custom_inspection_confirmed_by",
	):
		if meta.has_field(field):
			fields.append(field)
	return frappe.db.get_value("Project", project_name, fields, as_dict=True) or {}


def get_project_inspection_portal_context(project_name: str, customer: str) -> dict | None:
	"""Banner + confirm action for the customer shipment portal."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.portal import get_shipment_for_customer

	if not get_shipment_for_customer(project_name, customer):
		return None

	project = _project_inspection_fields(project_name)
	status = (project.get("custom_inspection_notification_status") or "Not Notified").strip()
	if status != "Notified":
		return None

	return {
		"show_banner": True,
		"title": _("Ready for inspection"),
		"message": _(
			"Please review your documents and permits for this shipment, then confirm when inspection is complete."
		),
		"can_confirm": True,
	}


def _shipment_portal_url(project_name: str) -> str:
	return get_url(f"/shipment?name={quote(project_name, safe='')}")


def _mark_inspection_confirmed(project_name: str, task_name: str, confirmed_by: str) -> None:
	now = now_datetime()
	task_updates = {
		"custom_inspection_confirmed_on": now,
		"custom_inspection_confirmed_by": confirmed_by,
	}
	frappe.db.set_value("Task", task_name, task_updates, update_modified=True)

	project_updates = {
		"custom_inspection_notification_status": "Confirmed",
		"custom_inspection_confirmed_on": now,
		"custom_inspection_confirmed_by": confirmed_by,
	}
	meta = frappe.get_meta("Project")
	for field in project_updates:
		if not meta.has_field(field):
			project_updates.pop(field, None)
	if project_updates:
		frappe.db.set_value("Project", project_name, project_updates, update_modified=True)


@frappe.whitelist()
def notify_client_for_inspection(task_name: str) -> dict:
	"""Email the client and flag the Project as ready for inspection."""
	task = _get_inspection_task(task_name)
	project_name = task.project
	project = frappe.get_doc("Project", project_name)
	customer = project.customer
	if not customer:
		frappe.throw(_("This Project has no Customer — add one before notifying the client."))

	emails = get_customer_notification_emails(customer)
	if not emails:
		frappe.throw(
			_(
				"No email address found for this customer. Add a primary contact, customer email, or portal user."
			)
		)

	now = now_datetime()
	user = frappe.session.user
	frappe.db.set_value(
		"Task",
		task.name,
		{
			"custom_client_notified_on": now,
			"custom_client_notified_by": user,
		},
		update_modified=True,
	)

	project_updates = {
		"custom_inspection_notification_status": "Notified",
		"custom_inspection_notified_on": now,
	}
	meta = frappe.get_meta("Project")
	for field in list(project_updates):
		if not meta.has_field(field):
			project_updates.pop(field, None)
	if project_updates:
		frappe.db.set_value("Project", project_name, project_updates, update_modified=True)

	ref = display_ref_from_values(project.as_dict()) or project_name
	portal_url = _shipment_portal_url(project_name)
	subject = _("Your shipment is ready for inspection")
	message = frappe.render_template(
		"""
<p>{{ _("Hello") }},</p>
<p>{{ _("Your shipment") }} <strong>{{ ref }}</strong> {{ _("is ready for inspection.") }}</p>
<p>{{ _("Please sign in to the customer portal to review your documents and permits:") }}</p>
<p><a href="{{ portal_url }}">{{ portal_url }}</a></p>
<p>{{ _("Thank you,") }}<br>{{ _("CGM Worldwide Shipping") }}</p>
""",
		{"ref": ref, "portal_url": portal_url},
	)

	frappe.sendmail(recipients=emails, subject=subject, message=message, delayed=False)

	notified_by = frappe.db.get_value("User", user, "full_name") or user
	return {
		"ok": True,
		"notified_on": now,
		"notified_by": notified_by,
		"emails": emails,
		"message": _("Client notified for inspection."),
	}


@frappe.whitelist()
def confirm_client_inspection_from_task(task_name: str) -> dict:
	"""Operations confirms the client has completed inspection (same effect as portal confirm)."""
	task = _get_inspection_task(task_name)
	if task.custom_inspection_confirmed_on:
		frappe.throw(_("Inspection has already been confirmed for this shipment."))

	user = frappe.session.user
	full_name = frappe.db.get_value("User", user, "full_name") or user
	confirmed_by = f"{full_name} ({user})"
	_mark_inspection_confirmed(task.project, task.name, confirmed_by)

	return {
		"ok": True,
		"confirmed_on": now_datetime(),
		"confirmed_by": confirmed_by,
		"message": _("Inspection marked as complete."),
	}


@frappe.whitelist()
def confirm_inspection_via_portal(project: str) -> dict:
	"""Customer confirms inspection complete from the shipment portal."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
		customer_for_user,
		get_shipment_for_customer,
	)

	customer = customer_for_user(frappe.session.user)
	if not customer:
		raise frappe.PermissionError(_("No customer is linked to your account."))

	if not get_shipment_for_customer(project, customer):
		raise frappe.PermissionError(_("You can only confirm inspection on your own shipments."))

	project_row = _project_inspection_fields(project)
	status = (project_row.get("custom_inspection_notification_status") or "").strip()
	if status != "Notified":
		frappe.throw(_("This shipment is not awaiting inspection confirmation."))

	inspection_task = get_inspection_task_for_project(project)
	if not inspection_task:
		frappe.throw(_("Inspection task not found on this shipment."))
	if inspection_task.custom_inspection_confirmed_on:
		frappe.throw(_("Inspection has already been confirmed."))

	user = frappe.get_cached_doc("User", frappe.session.user)
	confirmed_by = user.full_name or user.first_name or frappe.session.user
	_mark_inspection_confirmed(project, inspection_task.name, confirmed_by)

	return {
		"ok": True,
		"message": _("Thank you — your inspection confirmation has been recorded."),
	}
