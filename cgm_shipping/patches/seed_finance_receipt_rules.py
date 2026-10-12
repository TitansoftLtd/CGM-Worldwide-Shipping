"""Move the receipt requirement out of the code and into CGM Shipping Settings.

Why: the receipt is the one document CGM cannot produce itself, and it does not
always arrive. A client who pays his own entry slip often never sends the proof
back, so the Entry finance task stayed Open until someone chased him
(TASK-2026-00471); the shipping line does not always issue a receipt for a
payment CGM has already evidenced with its bank POP, so Shipping Line tasks
stalled the same way (TASK-2026-01058). Both waits were hardcoded.

What: seeds one rule per payment kind under Settings > Finance receipts - the
receipt is not required on the client-pays path, and Shipping Line does not
require it at all (its POP still does). Finance changes any of this in Desk.
Also relabels the Entry Slip receipt row to "Entry Slip POP", which is what is
actually filed there: 24 of the 30 attached rows are named "... DUTY POP".

Tasks already waiting only on a receipt complete themselves when someone next
opens or saves them - nothing is bulk-completed here.

Idempotent. One-time - retire per docs/guides/patches.md once staging and
production Patch Log show it.
"""

import frappe

# (payment kind, required when the company pays, required when the client pays)
DEFAULT_RULES: tuple[tuple[str, int, int], ...] = (
	("UCR", 1, 0),
	("ENTRY_SLIP", 1, 0),
	("Shipping Line", 0, 0),
	("KPA", 1, 0),
	("CFS", 1, 0),
)

OLD_ENTRY_LABEL = "Entry Slip Receipt"
NEW_ENTRY_LABEL = "Entry Slip POP"


def execute():
	seed_rules()
	relabel_entry_rows()
	retire_duplicate_seeded_charges()


def seed_rules():
	if not frappe.db.exists("DocType", "Finance Receipt Rule"):
		return
	settings = frappe.get_single("CGM Shipping Settings")
	if not settings.meta.has_field("custom_finance_receipt_rules"):
		return
	have = {
		(row.payment_kind or "").strip()
		for row in settings.get("custom_finance_receipt_rules") or []
	}
	added = 0
	for kind, company, client in DEFAULT_RULES:
		if kind in have or not frappe.db.exists("Payment Kind", kind):
			continue
		settings.append(
			"custom_finance_receipt_rules",
			{
				"payment_kind": kind,
				"required_when_company_pays": company,
				"required_when_client_pays": client,
			},
		)
		added += 1
	if added:
		settings.save(ignore_permissions=True)
		print(f"Finance receipts: seeded {added} rule(s)")


def relabel_entry_rows():
	"""The Entry Slip receipt row holds a duty POP - name it that way."""
	if frappe.db.exists("DocType", "Clearance Charge Item") and frappe.db.exists(
		"Clearance Charge Item", OLD_ENTRY_LABEL
	):
		if frappe.db.exists("Clearance Charge Item", NEW_ENTRY_LABEL):
			# Both exist: point the rows at the new one and retire the old.
			frappe.db.set_value(
				"Task Finance Line",
				{"charge_item": OLD_ENTRY_LABEL},
				"charge_item",
				NEW_ENTRY_LABEL,
				update_modified=False,
			)
			frappe.db.set_value(
				"Clearance Charge Item", OLD_ENTRY_LABEL, "is_active", 0, update_modified=False
			)
		else:
			frappe.rename_doc(
				"Clearance Charge Item",
				OLD_ENTRY_LABEL,
				NEW_ENTRY_LABEL,
				force=True,
				show_alert=False,
			)
			frappe.db.set_value(
				"Clearance Charge Item",
				NEW_ENTRY_LABEL,
				"description",
				"Proof of payment for the entry taxes (duty POP).",
				update_modified=False,
			)

	rows = frappe.get_all(
		"Task Finance Line",
		filters={"payment_item": "ENTRY_SLIP", "line_type": "Receipt", "line_label": OLD_ENTRY_LABEL},
		pluck="name",
	)
	for name in rows:
		frappe.db.set_value(
			"Task Finance Line", name, "line_label", NEW_ENTRY_LABEL, update_modified=False
		)
	if rows:
		parents = frappe.get_all(
			"Task Finance Line", filters={"name": ("in", rows)}, pluck="parent"
		)
		for parent in set(parents):
			frappe.clear_document_cache("Task", parent)
		print(f"Finance receipts: relabelled {len(rows)} Entry Slip row(s) to {NEW_ENTRY_LABEL}")


def retire_duplicate_seeded_charges():
	"""Deactivate a seeded charge that duplicates one ops renamed.

	Seeding checked the charge name alone, so after ops renamed "UCR Receipt" to
	"UCR POP" - a POP is what Finance files - the next migrate put "UCR Receipt"
	back as a second active charge for UCR + Receipt. Which of the two new rows
	picked up then depended on which had been edited least recently. Only a
	duplicate this app created, older sibling present and nothing pointing at it,
	is retired, and it is deactivated rather than deleted so it can be brought back.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.clearance_charge_item import (
		DEFAULT_CLEARANCE_CHARGE_ITEMS,
	)

	if not frappe.db.exists("DocType", "Clearance Charge Item"):
		return
	retired = []
	for spec in DEFAULT_CLEARANCE_CHARGE_ITEMS:
		name = (spec.get("charge_name") or "").strip()
		if not name or not frappe.db.exists("Clearance Charge Item", name):
			continue
		if not frappe.db.get_value("Clearance Charge Item", name, "is_active"):
			continue
		if frappe.db.count("Task Finance Line", {"charge_item": name}):
			continue
		creation = frappe.db.get_value("Clearance Charge Item", name, "creation")
		older = frappe.db.get_value(
			"Clearance Charge Item",
			{
				"payment_kind": spec.get("payment_kind"),
				"line_type": spec.get("line_type"),
				"is_active": 1,
				"creation": ("<", creation),
				"name": ("!=", name),
			},
			"name",
		)
		if not older:
			continue
		frappe.db.set_value(
			"Clearance Charge Item", name, "is_active", 0, update_modified=False
		)
		retired.append(f"{name} (superseded by {older})")
	if retired:
		print("Finance receipts: deactivated duplicate charge item(s): " + ", ".join(retired))
