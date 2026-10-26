"""Drop the UI-built "Payroll Registers" report in favour of the app's "Payroll Register".

"Payroll Registers" was created through the desk (`is_standard = "No"`), so its script
lived only in the site database: nothing in git, nothing reviewed, and no way to ship a
fix to it. The report now lives in the app at
`cgm_worldwide_shipping/report/payroll_register`, so the database copy is removed to
leave one register rather than two near-identical ones.

Deleting a Report is not just one row. Sidebars, shortcuts, scheduled emails, dashboard
charts and report-level role overrides all name a report by its name, and a forced delete
would leave every one of them pointing at nothing. So each is cleared first, and what was
cleared is written to the Error Log, because a scheduled email that silently stops is
worse than one somebody was told about.

Guarded on `is_standard = "No"`: if a future deploy ever ships a standard report under
the old name, this leaves it alone. Idempotent. Retire per docs/guides/patches.md once
staging and production Patch Log show it.
"""

import frappe

OLD = "Payroll Registers"
NEW = "Payroll Register"

#: (doctype, fieldname) naming a report, and the companion field that must say "Report"
#: for the row to be about one. A plain Link needs no companion.
DEPENDENTS = (
	("Prepared Report", "report_name", None, None),
	("Auto Email Report", "report", None, None),
	("Custom Role", "report", None, None),
	("Dashboard Chart", "report_name", None, None),
	("Number Card", "report_name", None, None),
	("Sidebar Item", "link_to", "link_type", "Report"),
	("Workspace Sidebar Item", "link_to", "link_type", "Report"),
	("Workspace Link", "link_to", "link_type", "Report"),
	("Workspace Shortcut", "link_to", "type", "Report"),
	("Workspace", "link_to", None, None),
)


def execute() -> None:
	if not frappe.db.exists("Report", OLD):
		return

	if frappe.db.get_value("Report", OLD, "is_standard") != "No":
		# Shipped by an app, so not ours to delete.
		return

	if not frappe.db.exists("Report", NEW):
		# The replacement has not synced yet. Leaving the old report in place beats
		# removing the only payroll register on the site.
		frappe.log_error(
			title="CGM patch: Payroll Registers kept",
			message=f"{NEW!r} is not on this site yet, so {OLD!r} was left in place.",
		)
		return

	removed = _clear_dependents()
	frappe.delete_doc("Report", OLD, ignore_permissions=True, force=True)

	# Sidebars and workspaces are served from a cache that still holds the dead entry.
	frappe.clear_cache()

	if removed:
		frappe.log_error(
			title="CGM patch: Payroll Registers replaced",
			message=(
				f"{OLD!r} was removed in favour of {NEW!r}.\n\n"
				"These references to it were cleared and may need recreating against "
				f"{NEW!r}:\n" + "\n".join(f"- {line}" for line in removed)
			),
		)


def _clear_dependents() -> list[str]:
	"""Delete every row naming the old report. Returns what was deleted, for the log."""
	removed = []

	for doctype, fieldname, guard_field, guard_value in DEPENDENTS:
		if not frappe.db.exists("DocType", doctype):
			continue

		meta = frappe.get_meta(doctype)
		if not meta.has_field(fieldname):
			continue

		filters = {fieldname: OLD}
		if guard_field and meta.has_field(guard_field):
			filters[guard_field] = guard_value

		try:
			names = frappe.get_all(doctype, filters=filters, pluck="name")
		except Exception:
			# A doctype whose shape changed under us is not worth failing the deploy for.
			continue

		for name in names:
			removed.append(f"{doctype} {name}")
			if meta.istable:
				frappe.db.delete(doctype, {"name": name})
			else:
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)

	return removed
