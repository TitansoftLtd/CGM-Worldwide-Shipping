# Copyright (c) 2026, Titansoft Limited and contributors
# License: see license.txt
"""Helpers for rendering server-side datetimes that the browser can
re-format to the visitor's local timezone.

Stored datetimes are naive in the system timezone (the one set in System
Settings). CGM customers can track shipments from anywhere, so rather
than rely on each customer setting `time_zone` on their User profile, we
emit an absolute UTC instant in the rendered HTML and let the browser
render it in its current locale via the hydration JS in
`public/js/portal_localize_time.js`.

Used by the `{% from "templates/includes/portal_localize.html" import
local_datetime, local_date %}` macros on the customer portal templates.

`local_datetime_iso` is registered as a Jinja method in hooks.py so the
macros can call it directly.
"""

from __future__ import annotations

from datetime import datetime

try:
	from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
	from backports.zoneinfo import ZoneInfo

from frappe.utils import get_datetime, get_system_timezone


def _zoneinfo(tz_name):
	try:
		return ZoneInfo(tz_name)
	except Exception:
		return ZoneInfo("UTC")


def local_datetime_iso(value) -> str:
	"""Convert a system-tz naive datetime to a UTC ISO 8601 string.

	The output is what the browser passes to `new Date(...)`: an
	explicit-offset string the JS Date parser handles unambiguously.
	Returns "" on missing / unparseable input so the macro can decide
	whether to render anything at all.

	Registered as a Jinja global via the `jinja.methods` entry in
	hooks.py - templates call it via `local_datetime_iso(value)`.
	"""
	if not value:
		return ""
	dt = get_datetime(value)
	if dt is None:
		return ""
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=_zoneinfo(get_system_timezone() or "UTC"))
	return dt.astimezone(ZoneInfo("UTC")).isoformat()
