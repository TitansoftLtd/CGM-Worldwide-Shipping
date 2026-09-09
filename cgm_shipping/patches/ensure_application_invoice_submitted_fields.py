"""Stop repeat "invoice ready" alerts on Entry Slip / Shipping Line / KPA tasks.

Why: ``auto_submit_application_invoice_to_finance_if_needed`` only suppresses a
resend when the profile has an ``application_submitted_field``. UCR and permits
have one; Entry Slip, Shipping Line and KPA did not, so every later save of the
application task re-fired the "invoice ready — please verify and pay" Notification
to the whole Finance role (one shipment collected 78 copies).

What: create the three missing Check fields on Task, then backfill them to 1 for
application tasks that already carry an attached Invoice line, so live shipments
do not get one more alert after this ships.

Idempotent: yes — fields are create-if-missing, backfill only touches rows still 0.
"""

from __future__ import annotations

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import TASK_FINANCE_FIELD
from cgm_shipping.cgm_worldwide_shipping.customizations.project_layout import _ensure_cf

FIELDS = (
	{
		"fieldname": "custom_entry_invoice_submitted",
		"label": "Entry Slip Invoice Submitted to Finance",
		"fieldtype": "Check",
		"insert_after": "custom_ucr_invoice_submitted",
		"default": "0",
		"read_only": 1,
	},
	{
		"fieldname": "custom_shipping_line_invoice_submitted",
		"label": "Shipping Line Invoice Submitted to Finance",
		"fieldtype": "Check",
		"insert_after": "custom_entry_invoice_submitted",
		"default": "0",
		"read_only": 1,
	},
	{
		"fieldname": "custom_kpa_invoice_submitted",
		"label": "KPA Invoice Submitted to Finance",
		"fieldtype": "Check",
		"insert_after": "custom_shipping_line_invoice_submitted",
		"default": "0",
		"read_only": 1,
	},
)


def execute() -> None:
	for values in FIELDS:
		_ensure_cf("Task", values)
	frappe.db.commit()
	_backfill_submitted_flags()


def _backfill_submitted_flags() -> None:
	from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
		APPLICATION_FINANCE_PROFILES,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		ROLE_APPLICATION,
	)

	meta = frappe.get_meta("Task")
	if not meta.has_field("custom_task_role") or not meta.has_field("custom_payment_kind"):
		return

	updated = 0
	for profile in APPLICATION_FINANCE_PROFILES.values():
		field = profile.application_submitted_field
		if not field or not meta.has_field(field):
			continue
		names = frappe.get_all(
			"Task",
			filters={
				"custom_task_role": ROLE_APPLICATION,
				"custom_payment_kind": profile.payment_item,
				field: 0,
			},
			pluck="name",
		)
		if not names:
			continue
		# An attached Invoice line means Finance was already told at least once.
		# Blank payment_item matches any profile, as get_invoice_lines() reads it.
		with_invoice = set(
			frappe.get_all(
				"Task Finance Line",
				filters={
					"parenttype": "Task",
					"parentfield": TASK_FINANCE_FIELD,
					"parent": ("in", names),
					"line_type": "Invoice",
					"attachment": ("is", "set"),
					"payment_item": ("in", [profile.payment_item, "", None]),
				},
				pluck="parent",
			)
		)
		for name in with_invoice:
			frappe.db.set_value("Task", name, field, 1, update_modified=False)
			updated += 1

	if updated:
		frappe.db.commit()
