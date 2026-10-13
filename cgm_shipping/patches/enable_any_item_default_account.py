"""Open Item Default account pickers to every account on sites that already exist.

Why a patch and not just a field default: `default` on a DocField applies when a
document is created. CGM Shipping Settings is a Single that was created long ago,
so its stored value stays at 0 and the default never reaches it. Without this, the
setting would read as ticked on a fresh install and unticked everywhere real.

What it does: sets `allow_any_item_default_account` to 1, which offers every
account on the company for Default Expense Account and Default Income Account on an
Item or Item Group. ERPNext restricts those to Profit and Loss accounts, which
leaves no valid choice for a charge CGM accrues to a liability account and bills on
- shipping line and KPA charges are both Current Liability on this chart.

This widens what a picker offers and nothing else. It changes no existing Item, no
account and nothing already posted, and it is undone by unticking the setting.
Group and disabled accounts are still never offered, because neither can be posted
to.

Only touches a value that has never been set. Somebody who has deliberately
unticked it keeps their choice.

Idempotent. Retire per docs/guides/patches.md once staging and production Patch Log
show it.
"""

import frappe

DOCTYPE = "CGM Shipping Settings"
FIELD = "allow_any_item_default_account"

#: The name this setting shipped under before it was widened past liability
#: accounts. Cleared so a site does not keep a dead row nobody reads.
OLD_FIELD = "allow_liability_item_default_accounts"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		print(f"{DOCTYPE} is not installed; nothing to do.")
		return

	frappe.db.delete("Singles", {"doctype": DOCTYPE, "field": OLD_FIELD})

	# A Single stores its fields in `tabSingles`, so "never set" means no row at
	# all - which is different from a row holding 0, and only the first should be
	# switched on.
	#
	# Queried with SQL rather than `frappe.db.exists`, because `tabSingles` has no
	# `name` column and the ORM helpers quietly return nothing for it. That made
	# the guard always fall through, so the patch overrode a deliberate untick.
	stored = frappe.db.sql(
		"select 1 from `tabSingles` where doctype = %(doctype)s and field = %(field)s limit 1",
		{"doctype": DOCTYPE, "field": FIELD},
	)
	if stored:
		current = frappe.db.get_single_value(DOCTYPE, FIELD)
		print(f"{FIELD} already set to {current}; leaving it alone.")
		frappe.db.commit()
		return

	frappe.db.set_single_value(DOCTYPE, FIELD, 1)
	frappe.db.commit()
	print(f"{FIELD} switched on; every account is now offered as an Item Default.")
