"""Desk-owned workflow Notification routing (CGM Shipping Settings).

Code fires stable workflow events; Settings maps each event → Notification name.
Create or edit Notifications in Desk freely — migrates only seed missing defaults.
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
	OPERATIONAL_UPDATE_NOTIFICATION,
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
WORKFLOW_NOTIFICATIONS_FIELD = "custom_workflow_notifications"

# Keep string literals (not imports from sea_task_notifications) to avoid cycles.
_YOUR_TURN_FINANCE = "CGM Task - Your Turn Finance"
_YOUR_TURN_DECLARATION = "CGM Task - Your Turn Declaration"
_YOUR_TURN_DOCUMENTATION = "CGM Task - Your Turn Documentation"
_YOUR_TURN_OPERATIONS = "CGM Task - Your Turn Operations"
_YOUR_TURN_TRANSPORT = "CGM Task - Your Turn Transport"

# Stable event label (Settings) → default seeded Notification name (fallback).
WORKFLOW_NOTIFICATION_DEFAULTS: tuple[tuple[str, str, str], ...] = (
	("Finance Payment Action", FINANCE_PAYMENT_ACTION, "Generic finance payment handoff"),
	("Permit Invoices to Finance", PERMIT_INVOICES_TO_FINANCE, ""),
	("Permit Receipts Attach", PERMIT_RECEIPTS_FOR_DECLARANT, "After Journal Entry payment"),
	("Permit Receipts Verify", PERMIT_RECEIPTS_VERIFY_FINANCE, ""),
	("UCR Invoice to Finance", UCR_INVOICE_TO_FINANCE, ""),
	("UCR Receipt Attach", UCR_RECEIPT_FOR_DECLARANT, "After Journal Entry payment"),
	("UCR Receipt Verify", UCR_RECEIPT_VERIFY_FINANCE, ""),
	("Entry Invoice to Finance", ENTRY_INVOICE_TO_FINANCE, ""),
	("Entry Receipt Attach", ENTRY_RECEIPT_FOR_DECLARANT, "Optional receipt"),
	("Entry Receipt Verify", ENTRY_RECEIPT_VERIFY_FINANCE, ""),
	("Shipping Line Invoice to Finance", SHIPPING_LINE_INVOICE_TO_FINANCE, ""),
	("Shipping Line Receipt Attach", SHIPPING_LINE_RECEIPT_FOR_DECLARANT, "POP + receipt"),
	("Shipping Line Receipt Verify", SHIPPING_LINE_RECEIPT_VERIFY_FINANCE, ""),
	("KPA Invoice to Finance", KPA_INVOICE_TO_FINANCE, ""),
	("KPA Receipt Attach", KPA_RECEIPT_FOR_SUPERVISOR, ""),
	("KPA Receipt Verify", KPA_RECEIPT_VERIFY_FINANCE, ""),
	("Your Turn Finance", _YOUR_TURN_FINANCE, ""),
	("Your Turn Declaration", _YOUR_TURN_DECLARATION, ""),
	("Your Turn Documentation", _YOUR_TURN_DOCUMENTATION, ""),
	("Your Turn Operations", _YOUR_TURN_OPERATIONS, ""),
	("Your Turn Transport", _YOUR_TURN_TRANSPORT, ""),
	("Daily Status RAG Alert", DAILY_STATUS_RAG_ALERT, ""),
	("Operational Update", OPERATIONAL_UPDATE_NOTIFICATION, ""),
)


def default_notification_for_event(workflow_event: str) -> str | None:
	for event, name, _notes in WORKFLOW_NOTIFICATION_DEFAULTS:
		if event == workflow_event:
			return name
	return None


def event_for_default_notification(notification_name: str) -> str | None:
	for event, name, _notes in WORKFLOW_NOTIFICATION_DEFAULTS:
		if name == notification_name:
			return event
	return None


@frappe.request_cache
def _settings_notification_overrides() -> dict[str, str]:
	"""default Notification name → override Notification name from Settings."""
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return {}
	meta = frappe.get_meta("CGM Shipping Settings")
	if not meta.has_field(WORKFLOW_NOTIFICATIONS_FIELD):
		return {}

	settings = frappe.get_cached_doc("CGM Shipping Settings")
	overrides: dict[str, str] = {}
	for row in settings.get(WORKFLOW_NOTIFICATIONS_FIELD) or []:
		event = (row.get("workflow_event") or "").strip()
		notification = (row.get("notification") or "").strip()
		if not event or not notification:
			continue
		default_name = default_notification_for_event(event)
		if not default_name:
			continue
		if notification != default_name and frappe.db.exists("Notification", notification):
			overrides[default_name] = notification
	return overrides


def resolve_notification_name(notification_name: str | None) -> str | None:
	"""Resolve Desk override from CGM Shipping Settings → Workflow notifications."""
	if not notification_name:
		return notification_name
	return _settings_notification_overrides().get(notification_name, notification_name)


def ensure_workflow_notification_settings(settings=None) -> bool:
	"""Add missing event rows pointing at seeded defaults. Never changes existing rows."""
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return False
	if not frappe.db.exists("DocType", "CGM Workflow Notification Item"):
		return False

	if settings is None:
		settings = frappe.get_doc("CGM Shipping Settings")
	if not settings.meta.has_field(WORKFLOW_NOTIFICATIONS_FIELD):
		return False

	existing = {
		(row.workflow_event or "").strip()
		for row in (settings.get(WORKFLOW_NOTIFICATIONS_FIELD) or [])
		if row.workflow_event
	}
	changed = False
	for event, default_name, notes in WORKFLOW_NOTIFICATION_DEFAULTS:
		if event in existing:
			continue
		if default_name and not frappe.db.exists("Notification", default_name):
			# Seed Notification first; row can be added on a later migrate.
			continue
		settings.append(
			WORKFLOW_NOTIFICATIONS_FIELD,
			{
				"workflow_event": event,
				"notification": default_name,
				"notes": notes,
			},
		)
		changed = True

	if changed:
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)
	return changed
