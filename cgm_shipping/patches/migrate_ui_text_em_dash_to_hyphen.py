"""One-time: swap ' — ' for ' - ' in CGM text already stored in the database.

Why: the code templates now use a plain hyphen everywhere, but text that was
seeded into documents keeps the separator it was created with - field labels and
descriptions on Custom Fields, task template subjects, and the Task subjects
already copied from those templates.

What: a literal `" — "` -> `" - "` swap on

  * DocField (label, description, options) on CGM Worldwide Shipping doctypes
  * Custom Field / Property Setter owned by CGM Worldwide Shipping (label,
    description, options / value)
  * CGM Task Template Item (subject, description)
  * Task (subject)

Nothing else is touched, and no other app's customisations are in scope.

The DocField and Custom Field rows are re-imported from this app's own JSON on
every ``bench migrate``, and those files carried the separator as the escape
``\u2014`` - invisible to a plain text search. Both are fixed now, so a migrate
no longer puts the em dash back.

Idempotent: yes - re-running finds nothing. One-time data rewrite: retire once
staging + production Patch Log show success.
"""

from __future__ import annotations

import frappe

OLD = " — "
NEW = " - "
MODULE = "CGM Worldwide Shipping"

def _targets() -> tuple[tuple[str, tuple[str, ...], dict], ...]:
	"""(doctype, fields, extra filters) - built at run time so filters see the site."""
	cgm_doctypes = frappe.get_all("DocType", filters={"module": MODULE}, pluck="name")
	return (
		# Standard fields on this app's own doctypes; core fields stay out of scope.
		("DocField", ("label", "description", "options"), {"parent": ("in", cgm_doctypes)}),
		("Custom Field", ("label", "description", "options"), {"module": MODULE}),
		("Property Setter", ("value",), {"module": MODULE, "property": ("in", ("label", "description"))}),
		("CGM Task Template Item", ("subject", "description"), {}),
		("Task", ("subject",), {}),
	)


def execute() -> None:
	touched_doctypes: set[str] = set()

	for doctype, fields, extra in _targets():
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		for field in fields:
			if not meta.has_field(field):
				continue
			filters = dict(extra)
			filters[field] = ("like", f"%{OLD}%")
			try:
				rows = frappe.get_all(doctype, filters=filters, fields=["name", field])
			except Exception:
				frappe.log_error(
					title=f"CGM em dash sweep failed on {doctype}.{field}",
					message=frappe.get_traceback(),
				)
				continue
			for row in rows:
				value = row.get(field)
				if not value or OLD not in value:
					continue
				frappe.db.set_value(
					doctype, row.name, field, value.replace(OLD, NEW), update_modified=False
				)
				touched_doctypes.add(doctype)

	if touched_doctypes:
		frappe.db.commit()
		# Custom Field / Property Setter edits only reach the form after a cache clear.
		frappe.clear_cache()
