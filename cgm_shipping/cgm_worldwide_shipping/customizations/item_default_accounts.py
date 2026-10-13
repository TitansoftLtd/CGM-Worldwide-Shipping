"""Offer every account for Item Defaults, when Finance asks for it.

ERPNext offers only Profit and Loss accounts (plus a short list of asset types) for
Default Expense Account, and only Profit and Loss or Income accounts for Default
Income Account. That is the right default for a company that consumes what it buys.

CGM does not always consume it. Shipping line and KPA charges are accrued to
liability accounts - `Shipping Line Charges` and `KPA Charges` are both Current
Liability on this chart - because the charge is incurred on a client's behalf and
billed on. There is no point at which it belongs in an expense account, so an item
representing one of those charges has nowhere valid to point.

Rather than guess which of the remaining account types CGM will need next, the
setting opens the pickers to every account on the company. The restriction it
removes is a convenience, not a control: nothing downstream validates the account
type of an Item Default, so ERPNext's narrower list was only ever a shortlist.
Whoever sets an Item Default is choosing where money lands and is expected to know
which account they mean.

It is behind `allow_any_item_default_account` in CGM Shipping Settings. With the
setting off these queries return exactly what ERPNext returns, account for account,
so a site that has not asked for it sees no change.

The queries mirror ERPNext's own conditions rather than calling them and appending,
so paging and the search text keep working across the whole result set instead of
only the first page.
"""

from __future__ import annotations

import frappe

#: Account types ERPNext allows as a default expense account alongside P&L accounts.
EXPENSE_ACCOUNT_TYPES = (
	"Expense Account",
	"Fixed Asset",
	"Temporary",
	"Asset Received But Not Billed",
	"Capital Work in Progress",
)

#: Account types ERPNext allows as a default income account alongside P&L accounts.
INCOME_ACCOUNT_TYPES = ("Income Account", "Temporary")

SETTING = "allow_any_item_default_account"


def any_account_allowed() -> bool:
	"""True when Finance has opened the pickers to every account."""
	if not frappe.db.exists("DocType", "CGM Shipping Settings"):
		return False
	# A Single has no table, so `frappe.db.has_column` raises rather than
	# returning False.
	if not frappe.get_meta("CGM Shipping Settings").has_field(SETTING):
		return False
	return bool(frappe.db.get_single_value("CGM Shipping Settings", SETTING))


def _account_query(account_types: tuple[str, ...], txt, filters, start, page_len):
	filters = filters or {}
	# A group account is a heading in the tree and can never be posted to, and a
	# disabled one is out of use. Neither is ever a valid default, whatever the
	# setting says.
	conditions = ["acc.is_group = 0", "acc.disabled = 0"]
	values: dict = {}

	if not any_account_allowed():
		conditions.append(
			"(acc.report_type = 'Profit and Loss' or acc.account_type in %(account_types)s)"
		)
		values["account_types"] = account_types

	if filters.get("company"):
		conditions.append("acc.company = %(company)s")
		values["company"] = filters["company"]
	if txt:
		conditions.append("(acc.name like %(txt)s or acc.account_name like %(txt)s)")
		values["txt"] = f"%{txt}%"

	values["start"] = int(start or 0)
	values["page_len"] = int(page_len or 20)

	return frappe.db.sql(
		"""
		select acc.name, acc.account_type, acc.root_type
		from `tabAccount` acc
		where {conditions}
		order by acc.name
		limit %(page_len)s offset %(start)s
		""".format(conditions=" and ".join(conditions)),
		values,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def expense_account_query(doctype, txt, searchfield, start, page_len, filters):
	"""Default Expense Account: ERPNext's list, or every account when allowed."""
	return _account_query(EXPENSE_ACCOUNT_TYPES, txt, filters, start, page_len)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def income_account_query(doctype, txt, searchfield, start, page_len, filters):
	"""Default Income Account: ERPNext's list, or every account when allowed."""
	return _account_query(INCOME_ACCOUNT_TYPES, txt, filters, start, page_len)
