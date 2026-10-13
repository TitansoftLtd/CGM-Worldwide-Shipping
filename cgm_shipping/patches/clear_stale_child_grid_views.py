"""Drop saved grid layouts for child tables that gained a column.

Why: clicking the gear on a child table and choosing columns writes a `GridView`
entry into that user's `__UserSettings`. From then on the grid renders that saved
list and ignores `in_list_view` on the DocField entirely, so a column added later
never shows for that user. It is not caching and it is not a refresh problem - the
saved preference genuinely wins, silently, forever.

It bites exactly the wrong people: anyone who has customised a grid is someone who
uses that form often, and they are the ones who would never see the new column.

Multicurrency added **Currency** to both of these tables, and Expense Account was
brought into the Material Request grid at the same time. The layouts found on this
site were missing those columns entirely.

Worth knowing for next time: Frappe v16's grid has no column budget. It sizes
columns in pixels and scrolls horizontally, so adding one costs nothing and no
existing column has to give up its place.

What: removes only the entries listed in `AFFECTED` from each user's saved
GridView. Their layouts for other child tables, their list view settings and their
filters are untouched, and the next time they open the form they get the columns
the DocType now defines. Anyone who wants a different layout sets one again from
the same gear.

This resets a display preference. It changes no data and nothing posted.

Idempotent. Retire per docs/guides/patches.md once staging and production Patch Log
show it.
"""

import json

import frappe

#: (parent doctype whose user settings hold the layout, child table doctype)
AFFECTED = (
	("Material Request", "Material Request Item"),
	("Funding Request", "Funding Request Material Request"),
)


def _clear(parent: str, child: str) -> list[str]:
	rows = frappe.db.sql(
		"select user, data from `__UserSettings` where doctype = %(doctype)s",
		{"doctype": parent},
		as_dict=True,
	)

	cleared = []
	for row in rows:
		try:
			data = json.loads(row.data or "{}")
		except (TypeError, ValueError):
			# A settings blob we cannot read is not ours to rewrite.
			continue
		grid = data.get("GridView")
		if not isinstance(grid, dict) or child not in grid:
			continue

		grid.pop(child)
		# An empty GridView is noise; drop the key rather than leave {} behind.
		if not grid:
			data.pop("GridView")
		frappe.db.sql(
			"update `__UserSettings` set data = %(data)s where user = %(user)s and doctype = %(doctype)s",
			{"data": json.dumps(data), "user": row.user, "doctype": parent},
		)
		cleared.append(row.user)
	return cleared


def execute():
	touched = 0
	for parent, child in AFFECTED:
		cleared = _clear(parent, child)
		if cleared:
			touched += len(cleared)
			print(f"Cleared the saved {child} grid layout for: {', '.join(sorted(cleared))}")
		else:
			print(f"No saved {child} grid layout to clear.")

	frappe.db.commit()
	# User settings are cached per user; a stale cache would hide the change until
	# the next login.
	frappe.cache.delete_keys("_user_settings")
	print(f"{touched} saved layout(s) cleared.")
