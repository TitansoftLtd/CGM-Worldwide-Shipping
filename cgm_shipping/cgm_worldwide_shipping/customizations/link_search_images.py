"""Link pickers stop crashing for users who may only select a record.

Frappe 16.60 added photos to link search results: `add_images` reads the image field
with `dict(get_list(..., fields=["name", image_field], as_list=True))`. Its own guard
asks `has_permission(doctype, "read")`, but `get_list` decides columns separately and
drops anything beyond the search fields for a select-only user. Each row then comes
back with one value and `dict()` raises "dictionary update sequence element #0 has
length 1; 2 is required".

On production that is every User picker (Assign To, Allocated To) for anyone without
HR Manager or System Manager: Desk User may select a User, not read one. First seen
21 Nov 2026, the day the site moved to 16.60.2.

The guard asks the question `get_list` asks, `get_permitted_fields`, and skips the
photos when the image field is not on that list. Remove it once Frappe fixes
`add_images` upstream.
"""

from __future__ import annotations

import frappe

_MARK = "_cgm_link_search_images"


def image_field_readable(doctype: str) -> bool:
	"""True when `get_list` would return the image field for this user."""
	from frappe.model import get_permitted_fields

	image_field = frappe.get_meta(doctype).image_field
	return bool(image_field) and image_field in get_permitted_fields(doctype)


def ensure_link_search_images_guard() -> None:
	"""Wrap Frappe's `add_images`, once per process. A no-op on Frappe without it."""
	import frappe.desk.search as search

	original = getattr(search, "add_images", None)
	if original is None or getattr(original, _MARK, False):
		return

	def add_images(rows, doctype):
		if rows and not image_field_readable(doctype):
			return
		return original(rows, doctype)

	setattr(add_images, _MARK, True)
	search.add_images = add_images
