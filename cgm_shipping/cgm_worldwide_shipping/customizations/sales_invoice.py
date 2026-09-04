"""Sales Invoice approval workflow."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, cstr, get_url, getdate, now_datetime
from frappe.utils.user import get_users_with_role

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	SALES_INVOICE_APPROVED_BY_FIELD,
	SALES_INVOICE_CREDIT_NOTE_NAMING_SERIES,
	SALES_INVOICE_NAMING_SERIES,
	SALES_INVOICE_REJECTED_BY_FIELD,
	SALES_INVOICE_REJECTION_REASON_FIELD,
	SALES_INVOICE_SUBMITTABLE_STATES,
	SALES_INVOICE_WORKFLOW_STATE_APPROVED,
	SALES_INVOICE_WORKFLOW_STATE_CANCELLED,
	SALES_INVOICE_WORKFLOW_STATE_DRAFT,
	SALES_INVOICE_WORKFLOW_STATE_PENDING,
)

MANAGER_ROLE = "Accounts Manager"


def before_insert_sales_invoice(doc, method=None) -> None:
	"""Apply CGM invoice / credit-note naming series before autoname runs."""
	if doc.get("amended_from"):
		return
	doc.naming_series = (
		SALES_INVOICE_CREDIT_NOTE_NAMING_SERIES
		if cint(doc.get("is_return"))
		else SALES_INVOICE_NAMING_SERIES
	)


def parse_mmyy_naming_series_variable(doc, variable):
	"""Return month+year as MMYY (e.g. 0926 for September 2026)."""
	if doc and doc.get("posting_date"):
		dt = getdate(doc.posting_date)
	else:
		dt = now_datetime()
	return dt.strftime("%m%y")


def validate_sales_invoice(doc, method=None) -> None:
	validate_sales_invoice_project_reference(doc)
	validate_sales_invoice_workflow(doc)


def after_insert_sales_invoice(doc, method=None) -> None:
	from cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading import (
		link_deposit_sales_invoice_to_bl,
	)

	if cint(doc.get("is_return")):
		return

	bl_name = (doc.get("custom_cgm_source_bill_of_lading") or "").strip()
	if not bl_name:
		return
	link_deposit_sales_invoice_to_bl(
		doc.name,
		bl_name,
		(doc.get("custom_cgm_source_task") or "").strip() or None,
	)


def validate_sales_invoice_workflow(doc) -> None:
	if not doc.meta.has_field("workflow_state"):
		return

	state = (doc.workflow_state or "").strip()
	if doc.docstatus == 1:
		if not state:
			doc.workflow_state = SALES_INVOICE_WORKFLOW_STATE_APPROVED
		return
	if doc.docstatus == 2:
		if not state:
			doc.workflow_state = SALES_INVOICE_WORKFLOW_STATE_CANCELLED
		return
	if not state:
		doc.workflow_state = SALES_INVOICE_WORKFLOW_STATE_DRAFT


def validate_sales_invoice_project_reference(doc) -> None:
	if not doc.meta.has_field("custom_project_name"):
		return

	project = (cstr(doc.get("project")) or "").strip()
	project_name = (cstr(doc.get("custom_project_name")) or "").strip()
	if not project and not project_name:
		frappe.throw(_("Please select a Project or enter a Project Name."))


def before_submit_sales_invoice(doc, method=None) -> None:
	"""Guard against submitting without approval (Approve sets workflow_state then submits)."""
	if not doc.meta.has_field("workflow_state"):
		return
	if (doc.workflow_state or "").strip() not in SALES_INVOICE_SUBMITTABLE_STATES:
		frappe.throw(
			_("Submit this Sales Invoice only after it has been approved."),
			title=_("Approval Required"),
		)


def on_sales_invoice_cancel(doc, method=None) -> None:
	if not doc.meta.has_field("workflow_state"):
		return
	frappe.db.set_value(
		"Sales Invoice",
		doc.name,
		"workflow_state",
		SALES_INVOICE_WORKFLOW_STATE_CANCELLED,
		update_modified=False,
	)


def on_update_sales_invoice_workflow(doc, method=None) -> None:
	if not doc.meta.has_field("workflow_state"):
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	prev = (before.workflow_state or "").strip()
	curr = (doc.workflow_state or "").strip()
	if curr == prev:
		return

	if curr == SALES_INVOICE_WORKFLOW_STATE_PENDING:
		_clear_rejection_stamps(doc)
		_share_sales_invoice_with_managers(doc)
		_notify_accounts_managers_pending_review(doc)
	elif curr == SALES_INVOICE_WORKFLOW_STATE_APPROVED:
		_stamp_sales_invoice_approval(doc)
		ensure_approved_sales_invoice_submitted(doc)
		_notify_owner_approved(doc)
	elif (
		prev == SALES_INVOICE_WORKFLOW_STATE_PENDING
		and curr == SALES_INVOICE_WORKFLOW_STATE_DRAFT
	):
		_stamp_sales_invoice_rejection(doc)
		_notify_owner_rejected(doc)


def on_sales_invoice_update(doc, method=None) -> None:
	"""Safety net: Approved invoices must be submitted so ERPNext status (Unpaid…) applies."""
	if doc.docstatus != 0:
		return
	if (doc.get("workflow_state") or "").strip() != SALES_INVOICE_WORKFLOW_STATE_APPROVED:
		return
	ensure_approved_sales_invoice_submitted(doc)


def ensure_approved_sales_invoice_submitted(doc) -> None:
	"""Submit after approval so payment Status (Unpaid / Partly Paid / Paid) takes over."""
	if doc.docstatus != 0:
		return
	if (doc.get("workflow_state") or "").strip() != SALES_INVOICE_WORKFLOW_STATE_APPROVED:
		return
	if frappe.flags.get("cgm_si_submitting_after_approval"):
		return

	frappe.flags.cgm_si_submitting_after_approval = True
	try:
		doc.submit()
	except frappe.ValidationError:
		raise
	except Exception as exc:
		frappe.log_error(
			title="CGM: Sales Invoice submit after approval failed",
			message=frappe.get_traceback(),
		)
		frappe.throw(
			_("This invoice is approved but could not be submitted: {0}").format(str(exc)),
			title=_("Submit Failed"),
		)
	finally:
		frappe.flags.cgm_si_submitting_after_approval = False


def _sales_invoice_form_url(name: str) -> str:
	return get_url(f"/app/sales-invoice/{name}")


def _manager_users() -> list[str]:
	return sorted(
		user
		for user in (get_users_with_role(MANAGER_ROLE) or [])
		if user and user != "Guest"
	)


def _share_sales_invoice_with_managers(doc) -> None:
	for user in _manager_users():
		if user in {doc.owner, frappe.session.user}:
			continue
		frappe.share.add_docshare(
			doc.doctype,
			doc.name,
			user,
			read=1,
			write=0,
			notify=0,
		)


def _notify_accounts_managers_pending_review(doc) -> None:
	recipients = [u for u in _manager_users() if u != doc.owner]
	if not recipients:
		return
	subject = _("Sales Invoice {0} awaiting your approval").format(doc.name)
	message = frappe.render_template(
		"""
<p>{{ _("A Sales Invoice has been submitted for your review.") }}</p>
<p><strong>{{ doc.name }}</strong> · {{ doc.customer_name or doc.customer }}</p>
<p>{{ _("Approval status") }}: <strong>{{ _("Pending Approval") }}</strong></p>
<p><a href="{{ url }}">{{ _("Open Sales Invoice") }}</a></p>
""",
		{"doc": doc, "url": _sales_invoice_form_url(doc.name)},
	)
	_send_sales_invoice_mail(recipients, subject, message, doc)


def _notify_owner_approved(doc) -> None:
	if not doc.owner or doc.owner == frappe.session.user:
		return
	subject = _("Sales Invoice {0} approved and submitted").format(doc.name)
	message = frappe.render_template(
		"""
<p>{{ _("Your Sales Invoice has been approved and submitted.") }}</p>
<p><strong>{{ doc.name }}</strong></p>
<p>{{ _("Approval status") }}: <strong>{{ _("Approved") }}</strong></p>
<p>{{ _("Payment status") }}: <strong>{{ doc.status or _("Unpaid") }}</strong></p>
<p><a href="{{ url }}">{{ _("Open Sales Invoice") }}</a></p>
""",
		{"doc": doc, "url": _sales_invoice_form_url(doc.name)},
	)
	_send_sales_invoice_mail([doc.owner], subject, message, doc)


def _notify_owner_rejected(doc) -> None:
	if not doc.owner:
		return
	reason = (cstr(doc.get(SALES_INVOICE_REJECTION_REASON_FIELD)) or "").strip()
	subject = _("Sales Invoice {0} rejected — returned to Draft").format(doc.name)
	reason_block = (
		f"<p><strong>{_('Rejection reason')}:</strong> {frappe.utils.escape_html(reason)}</p>"
		if reason
		else ""
	)
	message = frappe.render_template(
		"""
<p>{{ _("Your Sales Invoice was rejected and returned to Draft for correction.") }}</p>
<p><strong>{{ doc.name }}</strong></p>
<p>{{ _("Approval status") }}: <strong>{{ _("Draft") }}</strong></p>
{{ reason_block | safe }}
<p><a href="{{ url }}">{{ _("Open Sales Invoice") }}</a></p>
""",
		{
			"doc": doc,
			"url": _sales_invoice_form_url(doc.name),
			"reason_block": reason_block,
		},
	)
	_send_sales_invoice_mail([doc.owner], subject, message, doc)


def _send_sales_invoice_mail(recipients: list[str], subject: str, message: str, doc) -> None:
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=subject,
			message=message,
			delayed=True,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)
	except Exception:
		frappe.log_error(
			title="CGM: Sales Invoice workflow email failed",
			message=frappe.get_traceback(),
		)


def _stamp_sales_invoice_approval(doc) -> None:
	updates = {
		SALES_INVOICE_APPROVED_BY_FIELD: frappe.session.user,
		SALES_INVOICE_REJECTED_BY_FIELD: None,
		SALES_INVOICE_REJECTION_REASON_FIELD: None,
	}
	for fieldname, value in updates.items():
		if doc.meta.has_field(fieldname):
			doc.db_set(fieldname, value, update_modified=False)


def _stamp_sales_invoice_rejection(doc) -> None:
	reason = (cstr(doc.get(SALES_INVOICE_REJECTION_REASON_FIELD)) or "").strip() or None
	updates = {
		SALES_INVOICE_REJECTED_BY_FIELD: frappe.session.user,
		SALES_INVOICE_APPROVED_BY_FIELD: None,
		SALES_INVOICE_REJECTION_REASON_FIELD: reason,
	}
	for fieldname, value in updates.items():
		if doc.meta.has_field(fieldname):
			doc.db_set(fieldname, value, update_modified=False)


def _clear_rejection_stamps(doc) -> None:
	updates = {
		SALES_INVOICE_REJECTED_BY_FIELD: None,
		SALES_INVOICE_REJECTION_REASON_FIELD: None,
	}
	for fieldname, value in updates.items():
		if doc.meta.has_field(fieldname) and doc.get(fieldname):
			doc.db_set(fieldname, value, update_modified=False)
