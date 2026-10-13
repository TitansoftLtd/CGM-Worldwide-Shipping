"""SMS for the shipment workflow.

Two sources, one sender:

1. Handoffs the code already announces by email (invoice to Finance, payment
   recorded, receipt to verify...). CGM Shipping Settings > Workflow
   notifications has a "Send SMS" tick per event. When it is on, a text goes out
   with the email. The handoffs in `HANDOFF_SMS` have an SMS Notification of
   their own, so the text is short and its recipients are set apart from the
   email's. Any other ticked event is texted from the email's subject line, to
   the email's recipients.

2. Steps that had no announcement at all. A step being completed told nobody -
   the only "your turn" alert fires when a task is reopened. `STEP_SMS` lists the
   sea import steps whose completion CGM wants texted, each backed by a
   Notification document so the wording and the recipients are edited in Desk.

Everything is off until someone switches it on: the ticks default to 0 and the
step Notifications are created disabled. The handoff ones are created enabled,
because their tick is the switch. A text costs money per recipient and
goes to every user holding the role, so the decision is left to the desk.

Sending never happens inside the save. The texts are queued after commit, one
gateway call per number, so a slow or failing gateway cannot delay or fail the
task that triggered it, and one bad number does not stop the rest.

A step completed by a direct database write (the automatic completions use
`frappe.db.set_value`) does not pass through here, so it sends nothing.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, strip_html

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	CFS_INVOICE_TO_FINANCE,
	CFS_RECEIPT_FOR_SUPERVISOR,
	ENTRY_INVOICE_TO_FINANCE,
	ENTRY_RECEIPT_FOR_DECLARANT,
	KPA_INVOICE_TO_FINANCE,
	KPA_RECEIPT_FOR_SUPERVISOR,
	PERMIT_INVOICES_TO_FINANCE,
	PERMIT_RECEIPTS_FOR_DECLARANT,
	SHIPPING_LINE_INVOICE_TO_FINANCE,
	SHIPPING_LINE_RECEIPT_FOR_DECLARANT,
	UCR_INVOICE_TO_FINANCE,
	UCR_RECEIPT_FOR_DECLARANT,
)

SEA_IMPORT_FLOW = "Sea Import Workflow"
OPPORTUNITY_APPROVAL_SMS = "CGM SMS - Opportunity Approval Needed"
OPPORTUNITY_PENDING_STATE = "Pending Approval"

# One text is 160 plain characters; a longer one is billed as two or more.
SMS_MAX_LENGTH = 160

_SHIPMENT = "{{ doc.cgm_shipment_name or doc.project or doc.name }}"

# (sequence no completed, Notification name, roles, text). Sea import only.
# The roles are the seed; edit recipients on the Notification afterwards.
STEP_SMS: tuple[tuple[int, str, tuple[str, ...], str], ...] = (
	(
		1,
		"CGM SMS - Documents Received",
		("Declarant", "Field Operations Officers"),
		f"Documents received: {_SHIPMENT}",
	),
	(
		2,
		"CGM SMS - Documents Shared with Declarants",
		("Declarant",),
		f"Docs shared, create UCR: {_SHIPMENT}",
	),
	(
		8,
		"CGM SMS - Final Clearance Documents Received",
		("Declarant", "Field Operations Officers", "Operations Manager"),
		f"Final clearance docs received: {_SHIPMENT}",
	),
	(
		13,
		"CGM SMS - Entry Ready",
		("Field Operations Officers",),
		f"Entry paid and ready: {_SHIPMENT}",
	),
	(
		14,
		"CGM SMS - Delivery Order Lodged",
		("Declarant", "Field Operations Officers", "Senior Supervisor", "Operations Manager", "Director"),
		f"Delivery order attached: {_SHIPMENT}",
	),
	(
		15,
		"CGM SMS - Post-Clearance Permits Ready",
		("Field Operations Officers",),
		f"Permits in, start field clearance: {_SHIPMENT}",
	),
	(
		17,
		"CGM SMS - Obtain KPA Invoice",
		("Senior Supervisor",),
		f"Clearance done, get KPA invoice: {_SHIPMENT}",
	),
	(
		19,
		"CGM SMS - Book Trucks",
		("Field Operations Officers",),
		f"Payments done, book trucks: {_SHIPMENT}",
	),
	(
		20,
		"CGM SMS - Load Trucks and Exit Port",
		("Field Operations Officers",),
		f"Trucks booked, load and exit port: {_SHIPMENT}",
	),
	(
		21,
		"CGM SMS - Trucks Exited Port",
		("Tracking Officer",),
		f"Trucks exited port, start tracking: {_SHIPMENT}",
	),
)

# Roles seeded when the handoff's email Notification has none to copy.
_FINANCE_FALLBACK = ("Finance User",)

# (email Notification the event fires, SMS Notification name, roles, text).
# roles None = copy the email Notification's roles when the SMS one is created.
# "Paid" texts go to whoever acts next, which is not who the email goes to.
HANDOFF_SMS: tuple[tuple[str, str, tuple[str, ...] | None, str], ...] = (
	(UCR_INVOICE_TO_FINANCE, "CGM SMS - UCR Invoice to Finance", None, f"UCR invoice, verify and pay: {_SHIPMENT}"),
	(
		UCR_RECEIPT_FOR_DECLARANT,
		"CGM SMS - UCR Paid",
		("Declarant",),
		f"UCR paid, attach receipt and IDF: {_SHIPMENT}",
	),
	(
		PERMIT_INVOICES_TO_FINANCE,
		"CGM SMS - Permit Invoices to Finance",
		None,
		f"Permit invoices, verify and pay: {_SHIPMENT}",
	),
	(
		PERMIT_RECEIPTS_FOR_DECLARANT,
		"CGM SMS - Permits Paid",
		("Declarant",),
		f"Permits paid, attach receipts and permits: {_SHIPMENT}",
	),
	(
		SHIPPING_LINE_INVOICE_TO_FINANCE,
		"CGM SMS - Shipping Line Invoice to Finance",
		None,
		f"Shipping line invoice, verify and pay: {_SHIPMENT}",
	),
	(
		SHIPPING_LINE_RECEIPT_FOR_DECLARANT,
		"CGM SMS - Shipping Line Paid",
		("Documentation",),
		f"Shipping line paid, POP shared: {_SHIPMENT}",
	),
	(
		ENTRY_INVOICE_TO_FINANCE,
		"CGM SMS - Entry Invoice to Finance",
		None,
		f"Entry slip invoice, verify and pay: {_SHIPMENT}",
	),
	(
		ENTRY_RECEIPT_FOR_DECLARANT,
		"CGM SMS - Entry Slip Paid",
		("Declarant",),
		f"Entry slip paid, attach entry and receipt: {_SHIPMENT}",
	),
	(KPA_INVOICE_TO_FINANCE, "CGM SMS - KPA Invoice to Finance", None, f"KPA invoice, verify and pay: {_SHIPMENT}"),
	(KPA_RECEIPT_FOR_SUPERVISOR, "CGM SMS - KPA Paid", ("Senior Supervisor",), f"KPA paid: {_SHIPMENT}"),
	(CFS_INVOICE_TO_FINANCE, "CGM SMS - CFS Invoice to Finance", None, f"CFS invoice, verify and pay: {_SHIPMENT}"),
	(CFS_RECEIPT_FOR_SUPERVISOR, "CGM SMS - CFS Paid", ("Senior Supervisor",), f"CFS paid: {_SHIPMENT}"),
)


# ------------------------------------------------------------------
# Sending
# ------------------------------------------------------------------


def normalise_mobile(number: str | None) -> str:
	"""Kenyan numbers as the gateway takes them: 2547XXXXXXXX. Others pass through.

	The gateway was tested with 254702822379. Staff numbers get typed as
	0702..., +254 702... or 254702..., and the first two are rejected as sent.
	"""
	digits = "".join(ch for ch in (number or "") if ch.isdigit())
	if not digits:
		return ""
	if digits.startswith("0") and len(digits) == 10:
		return "254" + digits[1:]
	if len(digits) == 9 and digits[0] in "71":
		return "254" + digits
	return digits


def sms_gateway_configured() -> bool:
	return bool(frappe.db.get_single_value("SMS Settings", "sms_gateway_url"))


def _sms_text(notification, doc, context) -> str:
	"""The Notification's message when it is an SMS one, else its subject line."""
	template = notification.message if notification.channel == "SMS" else notification.subject
	text = strip_html(frappe.render_template(template or "", context) or "")
	text = " ".join(text.split())
	if len(text) > SMS_MAX_LENGTH:
		text = text[: SMS_MAX_LENGTH - 3].rstrip() + "..."
	return text


def queue_notification_sms(notification, doc) -> int:
	"""Queue one text per recipient of this Notification. Returns how many were queued.

	Never raises: this runs inside task and opportunity saves.
	"""
	try:
		if isinstance(notification, str):
			if not frappe.db.exists("Notification", notification):
				return 0
			notification = frappe.get_doc("Notification", notification)
		if not notification.enabled or not sms_gateway_configured():
			return 0

		from frappe.email.doctype.notification.notification import get_context

		from cgm_shipping.cgm_worldwide_shipping.customizations.sea_task_notifications import (
			stamp_shipment_name_on_doc,
		)

		stamp_shipment_name_on_doc(doc)
		context = get_context(doc)
		numbers = notification.get_receiver_list(doc, context, "mobile_no", notification.get_mobile_no)
		numbers = sorted({n for n in (normalise_mobile(n) for n in numbers) if n})
		text = _sms_text(notification, doc, context)
		if not numbers or not text:
			return 0

		frappe.enqueue(
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_sms.deliver_sms",
			queue="short",
			enqueue_after_commit=True,
			numbers=numbers,
			text=text,
			source=notification.name,
		)
		return len(numbers)
	except Exception:
		frappe.log_error(title="CGM workflow SMS could not be queued", message=frappe.get_traceback())
		return 0


def deliver_sms(numbers: list[str], text: str, source: str = "") -> None:
	"""Background job: one gateway call per number, failures logged and skipped."""
	from frappe.core.doctype.sms_settings.sms_settings import _send_sms

	failed = []
	for number in numbers:
		try:
			_send_sms([number], text, success_msg=False)
		except Exception as exc:
			failed.append(f"{number}: {exc}")
	if failed:
		frappe.log_error(
			title=f"CGM workflow SMS failed: {source}"[:140],
			message=f"{text}\n\n" + "\n".join(failed),
		)


# ------------------------------------------------------------------
# Triggers
# ------------------------------------------------------------------


def handoff_sms_notification(default_notification_name: str | None) -> str | None:
	for email_name, sms_name, _roles, _text in HANDOFF_SMS:
		if email_name == default_notification_name:
			return sms_name
	return None


def send_sms_for_workflow_event(default_notification_name: str, notification, doc) -> int:
	"""Text a code-fired handoff when its Settings row asks for it.

	The handoff's own SMS Notification when there is one - disabling that
	Notification silences the text. Without one, the email's subject line goes
	to the email's recipients.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_notifications import (
		sms_enabled_for_notification,
	)

	if not sms_enabled_for_notification(default_notification_name):
		return 0
	sms_name = handoff_sms_notification(default_notification_name)
	if sms_name and frappe.db.exists("Notification", sms_name):
		return queue_notification_sms(sms_name, doc)
	return queue_notification_sms(notification, doc)


def step_sms_notification(task) -> str | None:
	if (task.get("custom_task_flow_key") or "") != SEA_IMPORT_FLOW:
		return None
	seq = cint(task.get("custom_sequence_no"))
	for step_seq, name, _roles, _text in STEP_SMS:
		if step_seq == seq:
			return name
	return None


def notify_step_completed_sms(task) -> int:
	"""Called when a task has just become Completed through a normal save."""
	name = step_sms_notification(task)
	return queue_notification_sms(name, task) if name else 0


def notify_opportunity_approval_sms(doc, _method=None) -> None:
	"""Opportunity sent for review: text whoever approves shipments."""
	if (doc.get("workflow_state") or "") != OPPORTUNITY_PENDING_STATE:
		return
	prev = doc.get_doc_before_save()
	if prev and (prev.get("workflow_state") or "") == OPPORTUNITY_PENDING_STATE:
		return
	queue_notification_sms(OPPORTUNITY_APPROVAL_SMS, doc)


# ------------------------------------------------------------------
# Seeding
# ------------------------------------------------------------------


def _sms_notification_specs() -> list[dict]:
	specs = [
		{"name": name, "document_type": "Task", "roles": roles, "message": text}
		for _seq, name, roles, text in STEP_SMS
	]
	for email_name, name, roles, text in HANDOFF_SMS:
		if roles is None:
			roles = tuple(
				frappe.get_all(
					"Notification Recipient",
					filters={"parent": email_name, "parenttype": "Notification", "receiver_by_role": ["is", "set"]},
					pluck="receiver_by_role",
				)
			) or _FINANCE_FALLBACK
		# Enabled from the start: the Send SMS tick on the event is the switch.
		specs.append({"name": name, "document_type": "Task", "roles": roles, "message": text, "enabled": 1})
	specs.append(
		{
			"name": OPPORTUNITY_APPROVAL_SMS,
			"document_type": "Opportunity",
			"roles": ("Operations Manager",),
			"message": "Approve shipment {{ doc.name }}: {{ doc.customer_name or doc.party_name or '-' }}",
		}
	)
	return specs


def ensure_workflow_sms_notifications() -> int:
	"""Create the SMS Notifications that are missing. Never touches an existing one.

	Event Custom, so Frappe never fires them by itself: the triggers above queue
	them, off the save. Step and opportunity texts are created disabled; handoff
	texts are created enabled and wait for their event's Send SMS tick.
	"""
	if not frappe.db.exists("DocType", "Notification"):
		return 0
	created = 0
	for spec in _sms_notification_specs():
		if frappe.db.exists("Notification", spec["name"]):
			continue
		notification = frappe.new_doc("Notification")
		notification.name = spec["name"]
		notification.subject = spec["name"]
		notification.document_type = spec["document_type"]
		notification.channel = "SMS"
		notification.event = "Custom"
		notification.enabled = cint(spec.get("enabled"))
		notification.message = spec["message"]
		for role in spec["roles"]:
			if frappe.db.exists("Role", role):
				notification.append("recipients", {"receiver_by_role": role})
		previous = frappe.flags.ignore_links
		frappe.flags.ignore_links = True
		try:
			notification.insert(ignore_permissions=True)
			created += 1
		finally:
			frappe.flags.ignore_links = previous
	return created
