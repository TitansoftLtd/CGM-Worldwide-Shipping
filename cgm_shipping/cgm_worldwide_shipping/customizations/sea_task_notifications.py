"""Seed catalog for sea clearance Task Notifications (create-if-missing only).

Templates here are applied only when a Notification does not exist yet. After
seeding, edit subject / message / recipients / sender in Desk — migrates will
not overwrite them. Runtime helpers below still stamp shipment name and map
department → Your Turn notification names.
"""
from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	DAILY_STATUS_RAG_ALERT,
	ENTRY_INVOICE_TO_FINANCE,
	ENTRY_RECEIPT_FOR_DECLARANT,
	ENTRY_RECEIPT_VERIFY_FINANCE,
	FINANCE_PAYMENT_ACTION,
	KPA_INVOICE_TO_FINANCE,
	KPA_RECEIPT_FOR_SUPERVISOR,
	KPA_RECEIPT_VERIFY_FINANCE,
	PERMIT_INVOICES_TO_FINANCE,
	PERMIT_RECEIPTS_FOR_DECLARANT,
	PERMIT_RECEIPTS_VERIFY_FINANCE,
	SHIPPING_LINE_INVOICE_TO_FINANCE,
	SHIPPING_LINE_RECEIPT_FOR_DECLARANT,
	SHIPPING_LINE_RECEIPT_VERIFY_FINANCE,
	UCR_INVOICE_TO_FINANCE,
	UCR_RECEIPT_FOR_DECLARANT,
	UCR_RECEIPT_VERIFY_FINANCE,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
	DEFAULT_ROLE_GROUPS,
	ROLE_GROUP_DECLARATION,
	ROLE_GROUP_DOCUMENTATION,
	ROLE_GROUP_FINANCE,
	ROLE_GROUP_OPERATIONS,
	ROLE_GROUP_TRANSPORT,
	roles_for_group,
)

# Generic "your turn" notifications keyed by role group.
SEA_TASK_YOUR_TURN_FINANCE = "CGM Task - Your Turn Finance"
SEA_TASK_YOUR_TURN_DECLARATION = "CGM Task - Your Turn Declaration"
SEA_TASK_YOUR_TURN_DOCUMENTATION = "CGM Task - Your Turn Documentation"
SEA_TASK_YOUR_TURN_OPERATIONS = "CGM Task - Your Turn Operations"
SEA_TASK_YOUR_TURN_TRANSPORT = "CGM Task - Your Turn Transport"

_SHIPMENT = "{{ doc.get('cgm_shipment_name') or doc.project or '—' }}"
_TASK_LINK = (
	"<p><a href=\"{{ frappe.utils.get_url_to_form('Task', doc.name) }}\">Open task</a>"
	"{% if doc.project %} · "
	"<a href=\"{{ frappe.utils.get_url_to_form('Project', doc.project) }}\">Open project</a>"
	"{% endif %}</p>"
)


def _roles(*groups: str) -> tuple[str, ...]:
	roles: list[str] = []
	seen: set[str] = set()
	for group in groups:
		for role in roles_for_group(group) or DEFAULT_ROLE_GROUPS.get(group, ("", ()))[1]:
			if role and role not in seen:
				seen.add(role)
				roles.append(role)
	return tuple(roles)


def _def(
	name: str,
	*,
	subject: str,
	message: str,
	roles: tuple[str, ...],
	document_type: str = "Task",
) -> dict:
	return {
		"name": name,
		"subject": subject,
		"message": message,
		"roles": roles,
		"document_type": document_type,
	}


def sea_task_notification_definitions() -> list[dict]:
	finance = _roles(ROLE_GROUP_FINANCE)
	declaration = _roles(ROLE_GROUP_DECLARATION)
	documentation = _roles(ROLE_GROUP_DOCUMENTATION)
	operations = _roles(ROLE_GROUP_OPERATIONS)
	transport = _roles(ROLE_GROUP_TRANSPORT)
	# Finance upload of receipts is Finance-owned; keep constant names for code.
	finance_or_declaration = _roles(ROLE_GROUP_FINANCE, ROLE_GROUP_DECLARATION)

	return [
		_def(
			FINANCE_PAYMENT_ACTION,
			subject=f"{{{{ doc.get('cgm_notification_action_label') or 'Payment action needed' }}}} — {_SHIPMENT}",
			message=(
				f"<p>Finance action is required on task <b>{{{{ doc.subject }}}}</b> "
				f"({{{{ doc.name }}}}) for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>Open the task to verify invoices, record payment (Journal Entry), "
				"or tick <b>Client will pay</b>.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			PERMIT_INVOICES_TO_FINANCE,
			subject=f"Permit invoices ready for payment — {_SHIPMENT}",
			message=(
				f"<p>Permit invoices were submitted for shipment <b>{_SHIPMENT}</b>.</p>"
				"{% if doc.get('custom_task_permits') %}"
				"<p>Permits: {% for row in doc.custom_task_permits %}"
				"{{ row.permit_type }}{% if not loop.last %}, {% endif %}{% endfor %}</p>"
				"{% endif %}"
				"<p>On <b>{{ doc.subject }}</b>: verify invoices, then use "
				"<b>Make Payment</b> (or <b>Client will pay</b>) on each permit row.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			PERMIT_RECEIPTS_FOR_DECLARANT,
			subject=f"Attach permit payment receipts — {_SHIPMENT}",
			message=(
				f"<p>Payment was recorded for permits on shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>, attach <b>Payment Receipt</b> on each Local "
				"permit row when available, then verify.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance_or_declaration,
		),
		_def(
			PERMIT_RECEIPTS_VERIFY_FINANCE,
			subject=f"Verify permit payment receipts — {_SHIPMENT}",
			message=(
				f"<p>Payment receipts were uploaded for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>, tick <b>Receipt Verified</b> on each permit row.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			UCR_INVOICE_TO_FINANCE,
			subject=f"UCR invoice ready — please verify and pay — {_SHIPMENT}",
			message=(
				f"<p>A <b>UCR Invoice</b> was submitted for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>: verify the invoice, then use "
				"<b>Make Payment</b> (or tick <b>Client will pay</b> on the invoice row).</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			UCR_RECEIPT_FOR_DECLARANT,
			subject=f"Attach UCR payment receipt — {_SHIPMENT}",
			message=(
				f"<p>UCR payment was recorded for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>, attach the <b>UCR Receipt</b> and verify it.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			UCR_RECEIPT_VERIFY_FINANCE,
			subject=f"Verify UCR payment receipt — {_SHIPMENT}",
			message=(
				f"<p>A <b>UCR Receipt</b> was uploaded for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>, tick <b>Verified by Finance</b> on the receipt row.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			ENTRY_INVOICE_TO_FINANCE,
			subject=f"Entry Slip invoice ready — please verify and pay — {_SHIPMENT}",
			message=(
				f"<p>An <b>Entry Slip Invoice</b> was submitted for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>: verify the invoice, then use "
				"<b>Make Payment</b> (or <b>Client will pay</b>). Receipt is optional.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			ENTRY_RECEIPT_FOR_DECLARANT,
			subject=f"Attach Entry Slip receipt (optional) — {_SHIPMENT}",
			message=(
				f"<p>Entry Slip payment was recorded for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>, you may attach the <b>Entry Slip Receipt</b> when available.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			ENTRY_RECEIPT_VERIFY_FINANCE,
			subject=f"Verify Entry Slip receipt — {_SHIPMENT}",
			message=(
				f"<p>An <b>Entry Slip Receipt</b> was uploaded for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>, verify the receipt row if present.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			SHIPPING_LINE_INVOICE_TO_FINANCE,
			subject=f"Shipping Line invoice ready — please verify and pay — {_SHIPMENT}",
			message=(
				f"<p>A <b>Shipping Line Invoice</b> was submitted for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>: verify the invoice, then use "
				"<b>Make Payment</b> (or <b>Client will pay</b>), then attach POP.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			SHIPPING_LINE_RECEIPT_FOR_DECLARANT,
			subject=f"Attach Shipping Line POP / receipt — {_SHIPMENT}",
			message=(
				f"<p>Shipping Line payment was recorded for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>, attach bank <b>POP</b>; Documentation then attaches "
				"the <b>Shipping Line Receipt</b> for Finance to verify.</p>"
				f"{_TASK_LINK}"
			),
			roles=_roles(ROLE_GROUP_FINANCE, ROLE_GROUP_DOCUMENTATION),
		),
		_def(
			SHIPPING_LINE_RECEIPT_VERIFY_FINANCE,
			subject=f"Verify Shipping Line receipt — {_SHIPMENT}",
			message=(
				f"<p>A <b>Shipping Line Receipt</b> was uploaded for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>, tick <b>Verified by Finance</b> on the receipt row.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			KPA_INVOICE_TO_FINANCE,
			subject=f"KPA invoice ready — please verify and pay — {_SHIPMENT}",
			message=(
				f"<p>A <b>KPA Invoice</b> was submitted for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>: verify the invoice, then use "
				"<b>Make Payment</b> (or <b>Client will pay</b>).</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			KPA_RECEIPT_FOR_SUPERVISOR,
			subject=f"Attach KPA payment receipt — {_SHIPMENT}",
			message=(
				f"<p>KPA payment was recorded for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>, attach the <b>KPA Receipt</b> when available.</p>"
				f"{_TASK_LINK}"
			),
			roles=_roles(ROLE_GROUP_FINANCE, ROLE_GROUP_OPERATIONS),
		),
		_def(
			KPA_RECEIPT_VERIFY_FINANCE,
			subject=f"Verify KPA payment receipt — {_SHIPMENT}",
			message=(
				f"<p>A <b>KPA Receipt</b> was uploaded for shipment <b>{_SHIPMENT}</b>.</p>"
				"<p>On <b>{{ doc.subject }}</b>, tick <b>Verified by Finance</b> on the receipt row.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			SEA_TASK_YOUR_TURN_FINANCE,
			subject=f"Your turn: {{{{ doc.subject }}}} — {_SHIPMENT}",
			message=(
				f"<p>Task <b>{{{{ doc.subject }}}}</b> is ready for <b>Finance</b> on shipment "
				f"<b>{_SHIPMENT}</b>.</p>"
				"<p>Open the task and complete the required finance actions.</p>"
				f"{_TASK_LINK}"
			),
			roles=finance,
		),
		_def(
			SEA_TASK_YOUR_TURN_DECLARATION,
			subject=f"Your turn: {{{{ doc.subject }}}} — {_SHIPMENT}",
			message=(
				f"<p>Task <b>{{{{ doc.subject }}}}</b> is ready for <b>Declaration</b> on shipment "
				f"<b>{_SHIPMENT}</b>.</p>"
				"<p>Open the task and complete the required declaration actions.</p>"
				f"{_TASK_LINK}"
			),
			roles=declaration,
		),
		_def(
			SEA_TASK_YOUR_TURN_DOCUMENTATION,
			subject=f"Your turn: {{{{ doc.subject }}}} — {_SHIPMENT}",
			message=(
				f"<p>Task <b>{{{{ doc.subject }}}}</b> is ready for <b>Documentation</b> on shipment "
				f"<b>{_SHIPMENT}</b>.</p>"
				"<p>Open the task and complete the required documentation actions.</p>"
				f"{_TASK_LINK}"
			),
			roles=documentation,
		),
		_def(
			SEA_TASK_YOUR_TURN_OPERATIONS,
			subject=f"Your turn: {{{{ doc.subject }}}} — {_SHIPMENT}",
			message=(
				f"<p>Task <b>{{{{ doc.subject }}}}</b> is ready for <b>Operations</b> on shipment "
				f"<b>{_SHIPMENT}</b>.</p>"
				"<p>Open the task and complete the required operations actions.</p>"
				f"{_TASK_LINK}"
			),
			roles=operations,
		),
		_def(
			SEA_TASK_YOUR_TURN_TRANSPORT,
			subject=f"Your turn: {{{{ doc.subject }}}} — {_SHIPMENT}",
			message=(
				f"<p>Task <b>{{{{ doc.subject }}}}</b> is ready for <b>Transport / Field Ops</b> on shipment "
				f"<b>{_SHIPMENT}</b>.</p>"
				"<p>Open the task and complete the required transport actions.</p>"
				f"{_TASK_LINK}"
			),
			roles=transport,
		),
		_def(
			DAILY_STATUS_RAG_ALERT,
			subject="Daily status RAG alert — {{ doc.name }}",
			message=(
				"<p>A Daily Status Update requires attention.</p>"
				"<p><a href=\"{{ frappe.utils.get_url_to_form('Daily Status Update', doc.name) }}\">"
				"Open Daily Status Update</a></p>"
			),
			roles=operations,
			document_type="Daily Status Update",
		),
	]


def stamp_shipment_name_on_doc(doc) -> None:
	"""Set doc.cgm_shipment_name for Jinja (project business name, not PROJ-####)."""
	if not doc:
		return
	project = getattr(doc, "project", None) or (doc.get("project") if hasattr(doc, "get") else None)
	if not project:
		doc.cgm_shipment_name = None
		return
	try:
		from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
			get_project_reference_by_name,
		)

		doc.cgm_shipment_name = get_project_reference_by_name(project) or project
	except Exception:
		# Fallback: Project.project_name when present.
		name = frappe.db.get_value("Project", project, "project_name") if frappe.db.exists("Project", project) else None
		doc.cgm_shipment_name = name or project


def your_turn_notification_for_department(department: str | None) -> str | None:
	"""Map Task.department to a Your Turn Notification name."""
	dept = (department or "").strip().lower()
	if not dept:
		return None
	mapping = (
		(("finance", "accounts"), SEA_TASK_YOUR_TURN_FINANCE),
		(("declaration", "declarant"), SEA_TASK_YOUR_TURN_DECLARATION),
		(("documentation", "document"), SEA_TASK_YOUR_TURN_DOCUMENTATION),
		(("operation",), SEA_TASK_YOUR_TURN_OPERATIONS),
		(("transport", "field", "fleet"), SEA_TASK_YOUR_TURN_TRANSPORT),
	)
	for stems, notification in mapping:
		if any(stem in dept for stem in stems):
			return notification
	return None


def ensure_sea_task_notifications(*, sync_message: bool = False) -> int:
	"""Seed missing sea Task Notifications only. Never overwrites Desk edits.

	``sync_message`` is ignored (kept for call-site compatibility). Returns count created.
	"""
	if not frappe.db.exists("DocType", "Notification"):
		return 0

	created = 0
	for spec in sea_task_notification_definitions():
		name = spec["name"]
		# Skip Daily Status if DocType missing on site.
		if spec["document_type"] != "Task" and not frappe.db.exists("DocType", spec["document_type"]):
			continue

		if frappe.db.exists("Notification", name):
			continue

		roles = [r for r in spec["roles"] if r and frappe.db.exists("Role", r)]
		if not roles:
			for fallback in ("Finance User", "Declarant", "System Manager"):
				if frappe.db.exists("Role", fallback):
					roles.append(fallback)
					break

		doc = frappe.new_doc("Notification")
		doc.name = name
		doc.subject = spec["subject"]
		doc.document_type = spec["document_type"]
		doc.channel = "Email"
		doc.event = "Custom"
		doc.enabled = 1
		doc.message = spec["message"]
		for role in roles:
			doc.append("recipients", {"receiver_by_role": role})
		frappe.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		created += 1

	return created
