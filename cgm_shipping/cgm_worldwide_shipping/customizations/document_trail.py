"""Document Trail: who did what to a document, and what looks wrong about it.

The page answers the question that used to need someone reading the database:
"this project is Completed and has no container - what happened?" It gathers
what the system already stores about one document and lays it out in order,
with warnings for the patterns that have actually gone wrong here.

Three things about the data are worth knowing before reading the code:

1. Field-level history only exists where the doctype has Track Changes on.
   Project, Task and Opportunity had it off, so nothing before the day it was
   switched on can be listed. Listing a doctype under Settings > Document trail
   switches it on (`ensure_change_history`).

2. A write made with `frappe.db.set_value` leaves no history row even then.
   That is exactly how PROJ-0037 was closed. The trail cannot name the button,
   but it can show the evidence - tasks sharing one timestamp, completed tasks
   with no completion date - and that is what the warnings are built from.

3. The warnings are fixed rules, not judgement. Each one states a fact that can
   be checked on the document. Nothing here guesses at intent.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, strip_html

SETTINGS_FIELD = "custom_document_trail_doctypes"

# Used when the settings table is empty, so the page works on a fresh install
# and an emptied table means "the defaults", never "nothing".
DEFAULT_DOCTYPES = ("Project", "Task", "Opportunity", "Sales Invoice", "Journal Entry")

# Same roles as the page itself (page/document_trail/document_trail.json).
PAGE_ROLES = ("System Manager", "Operations Manager", "Finance Manager")

# Tasks changed by one user this close together were written by one action.
BULK_WINDOW = timedelta(seconds=10)
# Smallest group worth calling out; two or three tasks do move together legitimately.
BULK_MIN_TASKS = 5
# How far a history row may sit from `modified` and still explain it.
SAME_SAVE = timedelta(seconds=5)

MAX_CHANGES_PER_EVENT = 8
MAX_VALUE_LENGTH = 90
MAX_VERSIONS = 300
MAX_COMMENTS = 300

CLOSED_TASK_STATUSES = ("Completed", "Cancelled")

COMMENT_TITLES = {
	"Comment": "Commented",
	"Assigned": "Assigned",
	"Assignment Completed": "Assignment completed",
	"Attachment": "Attached a file",
	"Attachment Removed": "Removed a file",
	"Workflow": "Workflow action",
	"Shared": "Shared",
	"Unshared": "Stopped sharing",
	"Submitted": "Submitted",
	"Cancelled": "Cancelled",
	"Deleted": "Deleted a linked record",
	"Info": "System note",
	"Edit": "Edited",
	"Label": "Changed a label",
}

# Fields shown in the header when the document has them, in this order.
HEADER_FIELDS = (
	"status",
	"workflow_state",
	"custom_shipment_status",
	"percent_complete",
	"project",
	"customer",
	"party_name",
	"posting_date",
	"grand_total",
	"total_debit",
	"completed_on",
	"completed_by",
	"amended_from",
)


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------


def trail_doctypes() -> list[str]:
	"""Document types the trail may be asked about, in the order they are listed."""
	names: list[str] = []
	try:
		settings = frappe.get_cached_doc("CGM Shipping Settings")
		if settings.meta.has_field(SETTINGS_FIELD):
			names = [row.document_type for row in settings.get(SETTINGS_FIELD) or [] if row.document_type]
	except Exception:
		names = []
	if not names:
		names = list(DEFAULT_DOCTYPES)
	seen: set[str] = set()
	out = []
	for name in names:
		if name in seen or not frappe.db.exists("DocType", name):
			continue
		seen.add(name)
		out.append(name)
	return out


def ensure_change_history(doctypes: list[str] | None = None) -> list[str]:
	"""Switch Track Changes on for the listed doctypes. Returns the ones changed.

	The trail has nothing to show for a doctype that keeps no history, and nobody
	adding a row to the settings table would know to go and tick a box in
	Customize Form as well.
	"""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	changed = []
	for doctype in doctypes or trail_doctypes():
		meta = frappe.get_meta(doctype)
		if meta.istable or meta.issingle or cint(meta.track_changes):
			continue
		make_property_setter(
			doctype,
			None,
			"track_changes",
			1,
			"Check",
			for_doctype=True,
			validate_fields_for_doctype=False,
		)
		frappe.clear_cache(doctype=doctype)
		changed.append(doctype)
	return changed


def ensure_document_trail_setup() -> None:
	"""Seed the default doctypes and keep their history on. Called on every migrate.

	On every migrate, not once: syncing custom/*.json replaces a doctype's
	property setters, which would silently switch the history back off.
	"""
	if not frappe.db.exists("DocType", "Document Trail DocType"):
		return
	settings = frappe.get_single("CGM Shipping Settings")
	if not settings.meta.has_field(SETTINGS_FIELD):
		return
	if not settings.get(SETTINGS_FIELD):
		for doctype in DEFAULT_DOCTYPES:
			if frappe.db.exists("DocType", doctype):
				settings.append(SETTINGS_FIELD, {"document_type": doctype})
		settings.flags.ignore_permissions = True
		settings.flags.ignore_mandatory = True
		settings.save()
	ensure_change_history()


def validate_trail_doctype_rows(settings) -> None:
	"""Reject rows the trail cannot serve, and drop repeats."""
	seen: set[str] = set()
	keep = []
	for row in settings.get(SETTINGS_FIELD) or []:
		if not row.document_type or row.document_type in seen:
			continue
		meta = frappe.get_meta(row.document_type)
		if meta.istable or meta.issingle:
			frappe.throw(
				_("{0} cannot be listed under Document trail: it is a {1}, not a document of its own.").format(
					frappe.bold(row.document_type),
					_("child table") if meta.istable else _("settings page"),
				)
			)
		seen.add(row.document_type)
		keep.append(row)
	if len(keep) != len(settings.get(SETTINGS_FIELD) or []):
		settings.set(SETTINGS_FIELD, keep)


# ------------------------------------------------------------------
# Warning rules (pure: plain dicts in, plain dicts out)
# ------------------------------------------------------------------


def _warning(text: str, level: str = "warning") -> dict:
	return {"level": level, "text": text}


def bulk_task_groups(tasks: list[dict]) -> list[dict]:
	"""Groups of closed tasks last changed by one user within a few seconds.

	A task worked through its form is saved on its own, so its timestamp is its
	own. Many closed tasks sharing one are the mark of a single action writing
	them all. Tasks still carrying their creation timestamp are left out: a
	project's tasks are all created together, and that is not a bulk close.
	"""
	candidates = []
	for task in tasks:
		if task.get("status") not in CLOSED_TASK_STATUSES:
			continue
		modified = get_datetime(task.get("modified"))
		created = get_datetime(task.get("creation"))
		if not modified or (created and modified - created < timedelta(seconds=60)):
			continue
		candidates.append((task.get("modified_by") or "", modified, task))
	candidates.sort(key=lambda c: (c[0], c[1]))

	groups: list[dict] = []
	current: list = []
	for user, modified, task in candidates:
		if current and (user != current[-1][0] or modified - current[-1][1] > BULK_WINDOW):
			groups.append(current)
			current = []
		current.append((user, modified, task))
	if current:
		groups.append(current)

	out = []
	for group in groups:
		if len(group) < BULK_MIN_TASKS:
			continue
		statuses = sorted({g[2].get("status") for g in group})
		out.append(
			{
				"user": group[0][0],
				"time": group[0][1],
				"count": len(group),
				"statuses": statuses,
				"tasks": [g[2].get("name") for g in group],
			}
		)
	return out


def task_warnings(task: dict) -> list[dict]:
	out = []
	if task.get("status") == "Completed" and not task.get("completed_on"):
		out.append(
			_warning(
				_(
					"This task is Completed but has no completion date, so it was not "
					"completed through the normal task steps."
				)
			)
		)
	return out


def project_warnings(
	project: dict,
	tasks: list[dict],
	tracker_count: int,
	container_rows: int,
	user_names: dict[str, str] | None = None,
) -> list[dict]:
	user_names = user_names or {}
	out = []
	total = len(tasks)

	for group in bulk_task_groups(tasks):
		who = user_names.get(group["user"]) or group["user"] or _("an unknown user")
		out.append(
			_warning(
				_(
					"{0} of {1} tasks were last changed by {2} within the same few seconds "
					"on {3}, all left as {4}. Tasks worked one at a time do not share a timestamp."
				).format(
					group["count"],
					total,
					who,
					frappe.utils.format_datetime(group["time"], "d MMM yyyy, HH:mm"),
					" / ".join(group["statuses"]),
				)
			)
		)

	undated = [t for t in tasks if t.get("status") == "Completed" and not t.get("completed_on")]
	if undated:
		out.append(
			_warning(
				_(
					"{0} completed task(s) have no completion date, so they were not "
					"completed through the normal task steps and their checks did not run."
				).format(len(undated))
			)
		)

	completed = "Completed" in (project.get("status"), project.get("custom_shipment_status"))
	open_tasks = [t for t in tasks if t.get("status") not in CLOSED_TASK_STATUSES]
	if completed and open_tasks:
		out.append(
			_warning(_("The project is Completed but {0} task(s) are still open.").format(len(open_tasks)))
		)

	if completed and (project.get("custom_mode_of_transport") or "") == "Sea" and container_rows:
		if not tracker_count:
			out.append(
				_warning(
					_(
						"The project is Completed and lists {0} container(s), but has no Container Tracker."
					).format(container_rows)
				)
			)
		if not cint(project.get("custom_port_arrival_confirmed")):
			out.append(_warning(_("The project is Completed but port arrival was never confirmed.")))

	return out


# ------------------------------------------------------------------
# Collecting events
# ------------------------------------------------------------------


def _event(time, user, kind: str, title: str, **extra) -> dict:
	return {"time": get_datetime(time), "user": user or "", "kind": kind, "title": title, **extra}


def _short(value) -> str:
	if value is None or value == "":
		return ""
	text = strip_html(str(value)).strip()
	text = " ".join(text.split())
	if len(text) > MAX_VALUE_LENGTH:
		text = text[: MAX_VALUE_LENGTH - 1] + "…"
	return text


def _label(meta, fieldname: str) -> str:
	if fieldname == "docstatus":
		return _("Document status")
	df = meta.get_field(fieldname)
	return (df.label if df and df.label else fieldname.replace("_", " ").capitalize()) or fieldname


def _version_event(version: dict, meta) -> dict | None:
	try:
		data = json.loads(version.get("data") or "{}")
	except ValueError:
		return None

	changes = []
	title = ""
	for fieldname, old, new in data.get("changed") or []:
		if fieldname == "docstatus":
			title = {(0, 1): _("Submitted"), (1, 2): _("Cancelled")}.get((cint(old), cint(new)), title)
			continue
		if fieldname in ("status", "workflow_state", "custom_shipment_status") and not title:
			title = _("{0}: {1} → {2}").format(_label(meta, fieldname), _short(old) or "-", _short(new) or "-")
		changes.append({"label": _label(meta, fieldname), "old": _short(old), "new": _short(new)})

	for row_change in data.get("row_changed") or []:
		table_field, idx, _row_name, row_changes = (list(row_change) + [None] * 4)[:4]
		table_df = meta.get_field(table_field)
		child_meta = frappe.get_meta(table_df.options) if table_df and table_df.options else None
		for fieldname, old, new in row_changes or []:
			label = _label(child_meta, fieldname) if child_meta else fieldname
			changes.append(
				{
					"label": _("{0}, row {1}: {2}").format(_label(meta, table_field), cint(idx) + 1, label),
					"old": _short(old),
					"new": _short(new),
				}
			)

	for key, word in (("added", _("Row added to {0}")), ("removed", _("Row removed from {0}"))):
		for entry in data.get(key) or []:
			table_field = entry[0] if entry else ""
			changes.append({"label": word.format(_label(meta, table_field)), "old": "", "new": ""})

	if not changes and not title:
		return None
	if not title:
		title = _("Changed {0} field(s)").format(len(changes)) if len(changes) != 1 else _("Changed {0}").format(
			changes[0]["label"]
		)
	more = max(0, len(changes) - MAX_CHANGES_PER_EVENT)
	return _event(
		version.get("creation"),
		version.get("owner"),
		"change",
		title,
		changes=changes[:MAX_CHANGES_PER_EVENT],
		more_changes=more,
	)


def _version_events(doctype: str, name: str, meta) -> list[dict]:
	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": doctype, "docname": name},
		fields=["creation", "owner", "data"],
		order_by="creation desc",
		limit_page_length=MAX_VERSIONS,
	)
	return [e for e in (_version_event(v, meta) for v in versions) if e]


def _comment_events(doctype: str, name: str) -> list[dict]:
	comments = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": doctype,
			"reference_name": name,
			"comment_type": ["not in", ["Like", "Bot"]],
		},
		fields=["creation", "owner", "comment_email", "comment_type", "content"],
		order_by="creation desc",
		limit_page_length=MAX_COMMENTS,
	)
	out = []
	for c in comments:
		kind = "comment" if c.comment_type == "Comment" else "activity"
		out.append(
			_event(
				c.creation,
				c.comment_email or c.owner,
				kind,
				_(COMMENT_TITLES.get(c.comment_type, c.comment_type or "Activity")),
				details=[_short(c.content)] if _short(c.content) else [],
			)
		)
	return out


def _grouped_task_events(tasks: list[dict]) -> list[dict]:
	"""Task creation, and any later moment many tasks were written together."""
	out = []
	by_creation: dict[tuple, list] = {}
	for task in tasks:
		created = get_datetime(task.get("creation"))
		if created:
			by_creation.setdefault((task.get("owner"), created.replace(second=0, microsecond=0)), []).append(task)
	for (owner, minute), group in by_creation.items():
		first = min(get_datetime(t.get("creation")) for t in group)
		out.append(_event(first, owner, "linked", _("{0} task(s) created").format(len(group))))

	for group in bulk_task_groups(tasks):
		out.append(
			_event(
				group["time"],
				group["user"],
				"bulk",
				_("{0} tasks changed together, left as {1}").format(group["count"], " / ".join(group["statuses"])),
				details=[_("No field history was recorded for this change.")],
			)
		)
	return out


def _project_extras(doc) -> tuple[list[dict], list[dict], list[dict]]:
	"""(events, warnings, related sections) for a Project."""
	task_fields = ["name", "subject", "status", "creation", "owner", "modified", "modified_by", "completed_on", "completed_by"]
	task_meta = frappe.get_meta("Task")
	has_seq = task_meta.has_field("custom_sequence_no")
	if has_seq:
		task_fields.append("custom_sequence_no")
	tasks = frappe.get_all(
		"Task",
		filters={"project": doc.name},
		fields=task_fields,
		order_by=("custom_sequence_no asc, creation asc" if has_seq else "creation asc"),
		limit_page_length=500,
	)

	trackers = []
	if frappe.db.exists("DocType", "Container Tracker"):
		trackers = frappe.get_all(
			"Container Tracker",
			filters={"project": doc.name},
			fields=["name", "status", "creation", "owner"],
			order_by="creation asc",
		)

	container_rows = len(
		[r for r in (doc.get("custom_container_information") or []) if (r.get("container_number") or "").strip()]
	)

	events = _grouped_task_events(tasks)
	for tracker in trackers:
		events.append(
			_event(
				tracker.creation,
				tracker.owner,
				"linked",
				_("Container Tracker {0} created").format(tracker.name),
				details=[_("Current status: {0}").format(tracker.status)] if tracker.status else [],
			)
		)
	if doc.get("custom_port_arrival_confirmed") and doc.get("custom_port_arrival_confirmed_on"):
		events.append(
			_event(
				doc.custom_port_arrival_confirmed_on,
				doc.get("custom_port_arrival_confirmed_by"),
				"activity",
				_("Port arrival confirmed"),
			)
		)

	users = {t.get(k) for t in tasks for k in ("modified_by", "completed_by")}
	warnings = project_warnings(doc.as_dict(), tasks, len(trackers), container_rows, _user_names(users))

	related = [
		{
			"title": _("Tasks ({0})").format(len(tasks)),
			"doctype": "Task",
			"columns": [_("Task"), _("Status"), _("Completed on"), _("Completed by"), _("Last changed"), _("Changed by")],
			"rows": [
				{
					"name": t.name,
					"cells": [
						((f"{cint(t.get('custom_sequence_no'))}. " if has_seq and t.get("custom_sequence_no") else "") + (t.subject or t.name)),
						t.status or "",
						str(t.completed_on or ""),
						t.completed_by or "",
						str(t.modified or ""),
						t.modified_by or "",
					],
					"flag": t.status == "Completed" and not t.completed_on,
				}
				for t in tasks
			],
			"datetime_columns": [4],
			"date_columns": [2],
			"user_columns": [3, 5],
		}
	]
	if trackers:
		related.append(
			{
				"title": _("Container Trackers ({0})").format(len(trackers)),
				"doctype": "Container Tracker",
				"columns": [_("Container"), _("Status"), _("Created"), _("Created by")],
				"rows": [
					{"name": t.name, "cells": [t.name, t.status or "", str(t.creation or ""), t.owner or ""], "flag": False}
					for t in trackers
				],
				"datetime_columns": [2],
				"date_columns": [],
				"user_columns": [3],
			}
		)
	return events, warnings, related


def _user_names(users) -> dict[str, str]:
	users = [u for u in set(users) if u]
	if not users:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "full_name"])
	return {r.name: r.full_name or r.name for r in rows}


def _header(doc, meta) -> list[dict]:
	facts = []
	if meta.is_submittable:
		facts.append(
			{"label": _("Document status"), "value": [_("Draft"), _("Submitted"), _("Cancelled")][cint(doc.docstatus)]}
		)
	for fieldname in HEADER_FIELDS:
		df = meta.get_field(fieldname)
		value = doc.get(fieldname) if df else None
		if value in (None, ""):
			continue
		if df.fieldtype in ("Currency", "Float", "Percent"):
			value = frappe.format_value(value, df, doc=doc)
			value = strip_html(str(value))
		facts.append({"label": _(df.label or fieldname), "value": str(value), "fieldname": fieldname})
	return facts


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------


@frappe.whitelist()
def get_trail_doctypes() -> list[str]:
	frappe.only_for(PAGE_ROLES)
	return trail_doctypes()


@frappe.whitelist()
def get_document_trail(doctype: str, name: str) -> dict:
	"""Everything the Document Trail page shows for one document."""
	frappe.only_for(PAGE_ROLES)
	if doctype not in trail_doctypes():
		frappe.throw(
			_("{0} is not listed under CGM Shipping Settings > Document trail.").format(frappe.bold(doctype))
		)
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} {1} was not found.").format(doctype, frappe.bold(name)), frappe.DoesNotExistError)

	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	meta = doc.meta

	events = [_event(doc.creation, doc.owner, "created", _("Created"))]
	version_events = _version_events(doctype, name, meta)
	events += version_events
	events += _comment_events(doctype, name)

	warnings: list[dict] = []
	related: list[dict] = []
	if doctype == "Project":
		extra_events, warnings, related = _project_extras(doc)
		events += extra_events
	elif doctype == "Task":
		warnings = task_warnings(doc.as_dict())

	if meta.is_submittable and cint(doc.docstatus) == 2:
		warnings.append(_warning(_("This document is cancelled."), "note"))
	if meta.has_field("amended_from") and doc.get("amended_from"):
		warnings.append(_warning(_("This document replaces {0}.").format(doc.amended_from), "note"))

	# The last change, when nothing above accounts for it.
	created = get_datetime(doc.creation)
	modified = get_datetime(doc.modified)
	if modified and created and modified - created > SAME_SAVE:
		explained = any(
			e["kind"] in ("change", "bulk", "activity") and abs(e["time"] - modified) <= SAME_SAVE for e in events
		)
		if not explained:
			events.append(
				_event(
					modified,
					doc.modified_by,
					"untracked",
					_("Last changed"),
					details=[_("No field history was recorded for this change.")],
				)
			)

	if not version_events and modified and created and modified - created > SAME_SAVE:
		warnings.append(
			_warning(
				_(
					"No field-by-field history exists for this document. Changes made before "
					"history was switched on for {0}, and changes written directly by the system, are not listed."
				).format(_(doctype)),
				"note",
			)
		)

	events.sort(key=lambda e: e["time"] or datetime.min)
	names = _user_names(
		[e["user"] for e in events] + [doc.owner, doc.modified_by] + [doc.get("completed_by")]
	)
	for e in events:
		e["user_name"] = names.get(e["user"]) or e["user"]
		e["time"] = str(e["time"]) if e["time"] else ""

	title_field = meta.get_title_field()
	return {
		"doctype": doctype,
		"name": doc.name,
		"title": str(doc.get(title_field) or doc.name) if title_field else doc.name,
		"facts": _header(doc, meta),
		"created": {"time": str(doc.creation), "user": doc.owner, "user_name": names.get(doc.owner) or doc.owner},
		"modified": {
			"time": str(doc.modified),
			"user": doc.modified_by,
			"user_name": names.get(doc.modified_by) or doc.modified_by,
		},
		"history_kept": bool(cint(meta.track_changes)),
		"warnings": warnings,
		"related": related,
		"events": events,
		"user_names": {**names, **_user_names(c for s in related for r in s["rows"] for i, c in enumerate(r["cells"]) if i in s["user_columns"])},
	}
