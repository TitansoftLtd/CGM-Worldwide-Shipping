"""Share regulatory fee invoices with the customer portal (low CPU).

Finance marks invoices as shared via lightweight ``db.set_value`` updates and
queues one email. Portal lists only rows with ``shared_with_client`` — no sync
jobs or polling.
"""

from __future__ import annotations

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, get_url, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CLIENT_PAID_FIELD,
	PERMIT_REGISTER_FIELD,
	TASK_FINANCE_FIELD,
	TASK_PERMITS_FIELD,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.inspection import (
	get_customer_notification_emails,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
	display_ref_from_values,
)


def _shipment_portal_url(project_name: str) -> str:
	return get_url(f"/shipment?name={quote(project_name, safe='')}")


def _assert_finance_can_share(task) -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
		ACTION_CONFIRM_CLIENT_PAID,
		ACTION_MAKE_PAYMENT,
		ACTION_VERIFY_INVOICE,
		flow_for_task,
		user_has_responsibility,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		is_sea_finance_payment_task,
	)

	if not is_sea_finance_payment_task(task):
		frappe.throw(_("Share with Client is only available on finance payment tasks."))
	if not task.project:
		frappe.throw(_("Link this task to a Project before sharing with the client."))

	flow = flow_for_task(task) or "Permit"
	allowed = (
		user_has_responsibility(flow, ACTION_VERIFY_INVOICE)
		or user_has_responsibility(flow, ACTION_MAKE_PAYMENT)
		or user_has_responsibility(flow, ACTION_CONFIRM_CLIENT_PAID)
	)
	if not allowed and frappe.session.user != "Administrator":
		frappe.throw(_("You do not have permission to share invoices with the client."))


def _mark_rows_shared(doctype: str, names: list[str], user: str, when) -> int:
	"""Stamp share flags without loading parent documents."""
	if not names:
		return 0
	values = {
		"shared_with_client": 1,
		"shared_by": user,
		"shared_on": when,
	}
	# One UPDATE … IN (…) when possible; fall back per-row if meta lacks fields.
	meta = frappe.get_meta(doctype)
	for field in values:
		if not meta.has_field(field):
			return 0
	for name in names:
		frappe.db.set_value(doctype, name, values, update_modified=False)
	return len(names)


def _shareable_finance_line_names(task) -> list[str]:
	if not task.meta.has_field(TASK_FINANCE_FIELD):
		return []
	if not frappe.get_meta("Task Finance Line").has_field("shared_with_client"):
		return []
	return [
		row.name
		for row in (task.get(TASK_FINANCE_FIELD) or [])
		if row.get("name")
		and (row.get("line_type") or "Invoice") == "Invoice"
		and row.get("attachment")
		and cint(row.get("verified"))
		and not cint(row.get("shared_with_client"))
	]


def _shareable_permit_row_names(task) -> list[str]:
	if not task.meta.has_field(TASK_PERMITS_FIELD):
		return []
	if not frappe.get_meta("Permit Register").has_field("shared_with_client"):
		return []
	return [
		row.name
		for row in (task.get(TASK_PERMITS_FIELD) or [])
		if row.get("name")
		and row.get("permit_type")
		and (row.get("origin") or "Local") != "Foreign"
		and row.get("payment_invoice")
		and cint(row.get("invoice_verified"))
		and not cint(row.get("shared_with_client"))
	]


def _mirror_permit_share_to_project(project: str, permit_types: list[str], user: str, when) -> None:
	"""Stamp Project permit rows by type — no Project.get_doc / save."""
	if not project or not permit_types:
		return
	if not frappe.get_meta("Project").has_field(PERMIT_REGISTER_FIELD):
		return
	if not frappe.get_meta("Permit Register").has_field("shared_with_client"):
		return

	rows = frappe.get_all(
		"Permit Register",
		filters={
			"parent": project,
			"parenttype": "Project",
			"parentfield": PERMIT_REGISTER_FIELD,
			"permit_type": ["in", permit_types],
		},
		pluck="name",
	)
	_mark_rows_shared("Permit Register", rows, user, when)


def _queue_share_email(project_name: str, labels: list[str]) -> dict:
	customer = frappe.db.get_value("Project", project_name, "customer")
	if not customer:
		return {"emailed": False, "reason": "no_customer"}

	emails = get_customer_notification_emails(customer)
	if not emails:
		return {"emailed": False, "reason": "no_email"}

	meta = frappe.get_meta("Project")
	fields = ["name", "project_name"]
	for field in (
		"custom_batch_no",
		"custom_bill_of_lading",
		"custom_bl_number",
		"custom_air_waybill",
		"custom_awb_number",
	):
		if meta.has_field(field):
			fields.append(field)
	project_vals = frappe.db.get_value(
		"Project",
		project_name,
		fields,
		as_dict=True,
	) or {"name": project_name}
	ref = display_ref_from_values(project_vals) or project_name
	portal_url = _shipment_portal_url(project_name)
	fee_list = ", ".join(labels) if labels else _("regulatory fee invoice(s)")

	subject = _("Invoice ready for payment — {0}").format(ref)
	message = frappe.render_template(
		"""
<p>{{ _("Hello") }},</p>
<p>{{ _("Finance has shared invoice(s) for your shipment") }}
<strong>{{ ref }}</strong> {{ _("so you can arrange payment:") }}</p>
<p><strong>{{ fee_list }}</strong></p>
<p>{{ _("Sign in to the customer portal to download the invoice(s):") }}</p>
<p><a href="{{ portal_url }}">{{ portal_url }}</a></p>
<p>{{ _("After you pay, please send your payment receipt to CGM so Finance can upload it and complete clearance.") }}</p>
<p>{{ _("Thank you,") }}<br>{{ _("CGM Worldwide Shipping") }}</p>
""",
		{"ref": ref, "portal_url": portal_url, "fee_list": fee_list},
	)

	# Queued send — keeps the desk request light.
	frappe.sendmail(
		recipients=emails,
		subject=subject,
		message=message,
		delayed=True,
		reference_doctype="Project",
		reference_name=project_name,
	)
	return {"emailed": True, "recipients": emails}


@frappe.whitelist()
def share_invoices_with_client(task_name: str, notify: int = 1) -> dict:
	"""Share verified fee invoices on this finance task with the customer portal.

	Uses ``db.set_value`` only (no parent document save loops). Email is queued.
	"""
	frappe.has_permission("Task", ptype="write", doc=task_name, throw=True)
	# Lightweight field fetch — avoid loading child tables twice if empty.
	task = frappe.get_doc("Task", task_name)
	_assert_finance_can_share(task)

	if not cint(task.get(CLIENT_PAID_FIELD)):
		frappe.throw(
			_(
				"Tick <b>Client will pay</b> first, then share the invoice. "
				"Sharing is for the client-pays path (no company Journal Entry)."
			)
		)

	user = frappe.session.user
	when = now_datetime()

	finance_names = _shareable_finance_line_names(task)
	permit_names = _shareable_permit_row_names(task)

	if not finance_names and not permit_names:
		already = _already_shared_labels(task)
		if already:
			email_info = {"emailed": False}
			if cint(notify):
				email_info = _safe_queue_share_email(task.project, already)
			message = _("Invoices already shared with the client.")
			if email_info.get("emailed"):
				message = _("Client notified again by email.")
			elif cint(notify) and email_info.get("reason") == "no_email":
				message += " " + _("Could not email — add a customer contact or portal user.")
			elif cint(notify) and email_info.get("reason") == "email_failed":
				message += " " + _("Portal share is fine; email could not be sent.")
			return {
				"ok": True,
				"shared": 0,
				"already_shared": already,
				"message": message,
				**email_info,
			}
		frappe.throw(
			_(
				"No verified invoices ready to share. Verify the invoice first "
				"(and tick <b>Client will pay</b> when the client settles the fee)."
			)
		)

	shared = 0
	shared += _mark_rows_shared("Task Finance Line", finance_names, user, when)
	shared += _mark_rows_shared("Permit Register", permit_names, user, when)

	permit_types = [
		row.permit_type
		for row in (task.get(TASK_PERMITS_FIELD) or [])
		if row.name in set(permit_names) and row.permit_type
	]
	_mirror_permit_share_to_project(task.project, permit_types, user, when)

	labels = _labels_for_shared(task, finance_names, permit_names)

	# Persist portal visibility before email — mail failures must not roll back share.
	frappe.db.commit()

	email_info = {"emailed": False}
	if cint(notify):
		email_info = _safe_queue_share_email(task.project, labels)

	message = _("Shared {0} invoice(s) on the customer portal.").format(shared)
	if email_info.get("emailed"):
		message += " " + _("Client notified by email.")
	elif cint(notify) and email_info.get("reason") == "no_email":
		message += " " + _("Could not email — add a customer contact or portal user.")
	elif cint(notify) and email_info.get("reason") == "email_failed":
		message += " " + _("Portal share is fine; email could not be sent.")

	return {
		"ok": True,
		"shared": shared,
		"labels": labels,
		"client_pays": True,
		"message": message,
		**email_info,
	}


def _safe_queue_share_email(project_name: str, labels: list[str]) -> dict:
	try:
		return _queue_share_email(project_name, labels)
	except Exception as exc:
		frappe.log_error(
			title="CGM: share-invoice email failed",
			message=frappe.get_traceback(),
		)
		return {"emailed": False, "reason": "email_failed", "error": str(exc)}


def _already_shared_labels(task) -> list[str]:
	labels: list[str] = []
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if (
			(row.get("line_type") or "Invoice") == "Invoice"
			and cint(row.get("shared_with_client"))
			and row.get("attachment")
		):
			labels.append(row.get("line_label") or row.get("payment_item") or _("Invoice"))
	for row in task.get(TASK_PERMITS_FIELD) or []:
		if cint(row.get("shared_with_client")) and row.get("payment_invoice"):
			labels.append(row.get("permit_type") or _("Permit invoice"))
	return labels


def _labels_for_shared(task, finance_names: list[str], permit_names: list[str]) -> list[str]:
	fin_set = set(finance_names)
	perm_set = set(permit_names)
	labels: list[str] = []
	for row in task.get(TASK_FINANCE_FIELD) or []:
		if row.name in fin_set:
			labels.append(row.get("line_label") or row.get("payment_item") or _("Invoice"))
	for row in task.get(TASK_PERMITS_FIELD) or []:
		if row.name in perm_set:
			labels.append(row.get("permit_type") or _("Permit invoice"))
	return labels


@frappe.whitelist()
def submit_client_fee_payment_receipt(
	project: str, source: str, row: str, file_url: str
) -> dict:
	"""Customer portal: client uploads payment receipt for a shared fee invoice.

	Stores the receipt on the finance Receipt line (or Permit payment_receipt)
	and stamps client_reported_paid — Finance can then complete settlement.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
		customer_for_user,
	)

	customer = customer_for_user(frappe.session.user)
	if not customer:
		raise frappe.PermissionError(_("No customer is linked to your account."))

	owner = frappe.db.get_value("Project", project, "customer")
	if not owner or owner != customer:
		raise frappe.PermissionError(_("You can only submit receipts for your own shipments."))

	file_url = (file_url or "").strip()
	if not file_url:
		frappe.throw(_("Upload a payment receipt first."))
	if not frappe.db.exists("File", {"file_url": file_url}):
		frappe.throw(_("Receipt file was not found. Please upload again."))

	when = now_datetime()
	if source == "finance_line":
		_submit_finance_line_receipt(project, row, file_url, when)
	elif source == "permit":
		_submit_permit_receipt(project, row, file_url, when)
	else:
		frappe.throw(_("Unknown invoice source."))

	frappe.db.commit()
	_queue_finance_receipt_notice(project, source, row)
	return {
		"ok": True,
		"message": _(
			"Thank you — your payment receipt was submitted. CGM Finance will confirm and continue clearance."
		),
	}


def _submit_finance_line_receipt(project: str, invoice_row: str, file_url: str, when) -> None:
	matched = frappe.db.sql(
		"""
		SELECT tfl.name, tfl.parent, tfl.payment_item, tfl.shared_with_client
		FROM `tabTask Finance Line` tfl
		INNER JOIN `tabTask` t ON t.name = tfl.parent AND tfl.parenttype = 'Task'
		WHERE tfl.name = %(row)s
			AND t.project = %(project)s
			AND tfl.line_type = 'Invoice'
		LIMIT 1
		""",
		{"row": invoice_row, "project": project},
		as_dict=True,
	)
	if not matched or not cint(matched[0].shared_with_client):
		frappe.throw(_("This invoice is not shared for client payment."))

	inv = matched[0]
	# Put receipt on the paired Receipt line (existing settlement path).
	receipt_name = frappe.db.get_value(
		"Task Finance Line",
		{
			"parent": inv.parent,
			"parenttype": "Task",
			"line_type": "Receipt",
			"payment_item": inv.payment_item,
		},
		"name",
	)
	if receipt_name:
		frappe.db.set_value(
			"Task Finance Line",
			receipt_name,
			{"attachment": file_url},
			update_modified=False,
		)
	else:
		task = frappe.get_doc("Task", inv.parent)
		task.append(
			TASK_FINANCE_FIELD,
			{
				"line_label": f"{inv.payment_item or 'Fee'} Receipt",
				"line_type": "Receipt",
				"payment_item": inv.payment_item,
				"attachment": file_url,
			},
		)
		task.flags.ignore_permissions = True
		task.save(ignore_permissions=True)

	updates = {}
	meta = frappe.get_meta("Task Finance Line")
	if meta.has_field("client_reported_paid"):
		updates["client_reported_paid"] = 1
	if meta.has_field("client_reported_on"):
		updates["client_reported_on"] = when
	if updates:
		frappe.db.set_value("Task Finance Line", inv.name, updates, update_modified=False)


def _submit_permit_receipt(project: str, permit_row: str, file_url: str, when) -> None:
	row = frappe.db.get_value(
		"Permit Register",
		{
			"name": permit_row,
			"parent": project,
			"parenttype": "Project",
			"parentfield": PERMIT_REGISTER_FIELD,
			"shared_with_client": 1,
		},
		["name", "permit_type"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("This permit invoice is not shared for client payment."))

	updates = {"payment_receipt": file_url}
	meta = frappe.get_meta("Permit Register")
	if meta.has_field("client_reported_paid"):
		updates["client_reported_paid"] = 1
	if meta.has_field("client_reported_on"):
		updates["client_reported_on"] = when
	frappe.db.set_value("Permit Register", row.name, updates, update_modified=False)

	if row.permit_type:
		task_rows = frappe.db.sql(
			"""
			SELECT pr.name
			FROM `tabPermit Register` pr
			INNER JOIN `tabTask` t ON t.name = pr.parent AND pr.parenttype = 'Task'
			WHERE t.project = %(project)s
				AND pr.permit_type = %(permit_type)s
			""",
			{"project": project, "permit_type": row.permit_type},
		)
		for (name,) in task_rows or []:
			frappe.db.set_value("Permit Register", name, updates, update_modified=False)


def _queue_finance_receipt_notice(project: str, source: str, row: str) -> None:
	"""Optional light notify — never blocks the portal response."""
	try:
		ref = display_ref_from_values(
			frappe.db.get_value("Project", project, ["name", "project_name"], as_dict=True)
			or {"name": project}
		) or project
		frappe.publish_realtime(
			"cgm_client_fee_receipt",
			{"project": project, "source": source, "row": row, "ref": ref},
			user="Administrator",
			after_commit=True,
		)
	except Exception:
		frappe.log_error(
			title="CGM: client fee receipt notice failed",
			message=frappe.get_traceback(),
		)
