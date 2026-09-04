# Copyright (c) 2026, Titansoft Limited and contributors
"""Customer and transporter feedback on a shipment (Project).

Feedback hangs off the Project. A party leaves one entry per shipment and may
tick the containers it is about - the `containers` child table narrows a rating
to particular boxes without turning it into a separate per-container record.

Portal users hold no role on `Portal Feedback`, so every write goes through
this module with `ignore_permissions=True` after the caller has proved the
shipment belongs to the party. Submitting again edits what they left before,
which is how a rating widget is expected to behave and keeps the ops list free
of duplicates.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	PORTAL_FEEDBACK_NOTIFICATION,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import send_notification
from cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates import is_portal_user

FEEDBACK_DOCTYPE = "Portal Feedback"

# Stars are offered in half steps, matching Frappe's Rating control.
RATING_MAX = 5
RATING_STEP = 0.5

PARTY_CUSTOMER = "Customer"
PARTY_TRANSPORTER = "Transporter"

FEEDBACK_CATEGORIES = (
	"Overall Service",
	"Communication",
	"Timeliness",
	"Documentation",
	"Container Handling",
	"Transport & Delivery",
	"Other",
)

FEEDBACK_STATUSES = ("New", "Acknowledged", "Resolved")

_FEEDBACK_FIELDS = [
	"name",
	"project",
	"submitted_by_party",
	"customer",
	"transporter",
	"submitted_by",
	"submitted_on",
	"rating",
	"category",
	"would_recommend",
	"comments",
	"status",
	"response",
	"responded_by",
	"responded_on",
]


def stars_from_rating(rating) -> float:
	"""Frappe stores Rating as 0-1; portals speak in stars, to the half."""
	value = flt(rating)
	if value <= 1:
		value = value * RATING_MAX
	return round(value / RATING_STEP) * RATING_STEP


def rating_from_stars(stars) -> float:
	value = flt(stars)
	if value <= 0 or value > RATING_MAX:
		frappe.throw(_("Give a rating between {0} and {1} stars.").format(RATING_STEP, RATING_MAX))
	# Snap to the half-star the widget can actually show.
	value = round(value / RATING_STEP) * RATING_STEP
	return value / RATING_MAX


def _feedback_containers(name: str) -> list[dict]:
	rows = frappe.get_all(
		"Portal Feedback Container",
		filters={"parent": name, "parenttype": FEEDBACK_DOCTYPE},
		fields=["container_tracker", "container_number"],
		order_by="idx asc",
		ignore_permissions=True,
	)
	return [
		{
			"container_tracker": r.container_tracker,
			"container_number": r.container_number or r.container_tracker,
		}
		for r in rows
	]


def serialize_feedback(row) -> dict:
	row = frappe._dict(row)
	submitted_on = row.get("submitted_on")
	responded_on = row.get("responded_on")
	containers = (
		[
			{
				"container_tracker": c.get("container_tracker"),
				"container_number": c.get("container_number") or c.get("container_tracker"),
			}
			for c in row.get("containers")
		]
		if row.get("containers")
		else _feedback_containers(row.name)
	)
	return {
		"name": row.name,
		"project": row.get("project") or "",
		"submitted_by_party": row.get("submitted_by_party") or "",
		"customer": row.get("customer") or "",
		"transporter": row.get("transporter") or "",
		"submitted_by": row.get("submitted_by") or "",
		"submitted_by_name": (
			frappe.utils.get_fullname(row.get("submitted_by")) if row.get("submitted_by") else ""
		),
		"submitted_on": str(submitted_on) if submitted_on else "",
		"rating": flt(row.get("rating")),
		"stars": stars_from_rating(row.get("rating")),
		"category": row.get("category") or "",
		"would_recommend": cint(row.get("would_recommend")),
		"comments": row.get("comments") or "",
		"containers": containers,
		"container_numbers": [c["container_number"] for c in containers],
		"status": row.get("status") or "New",
		"response": row.get("response") or "",
		"responded_by_name": (
			frappe.utils.get_fullname(row.get("responded_by")) if row.get("responded_by") else ""
		),
		"responded_on": str(responded_on) if responded_on else "",
	}


def project_container_options(project: str, limit_to: list[str] | None = None) -> list[dict]:
	"""Containers a party may tick on this shipment's feedback."""
	if not project or not frappe.db.exists("DocType", "Container Tracker"):
		return []
	filters: dict = {"project": project}
	if limit_to is not None:
		if not limit_to:
			return []
		filters["name"] = ("in", limit_to)
	rows = frappe.get_all(
		"Container Tracker",
		filters=filters,
		fields=["name", "container_number"],
		order_by="container_number asc",
		ignore_permissions=True,
	)
	return [
		{"value": r.name, "label": r.container_number or r.name}
		for r in rows
	]


def _clean_containers(
	containers, project: str, allowed: list[str] | None = None
) -> list[str]:
	"""Keep only containers that really sit on this shipment (and are allowed)."""
	if isinstance(containers, str):
		containers = frappe.parse_json(containers) if containers.strip() else []
	if not containers:
		return []

	names = [c for c in containers if c]
	valid = set(
		frappe.get_all(
			"Container Tracker",
			filters={"project": project, "name": ("in", names)},
			pluck="name",
			ignore_permissions=True,
		)
	)
	if allowed is not None:
		valid &= set(allowed)

	rejected = [n for n in names if n not in valid]
	if rejected:
		frappe.throw(
			_("These containers are not on this shipment: {0}").format(", ".join(rejected)),
			frappe.PermissionError,
		)
	# Preserve the order the party ticked them in, without duplicates.
	seen: set[str] = set()
	ordered: list[str] = []
	for n in names:
		if n in valid and n not in seen:
			seen.add(n)
			ordered.append(n)
	return ordered


def _validate_inputs(category: str | None, comments: str | None, stars) -> tuple[str, str]:
	category = (category or "Overall Service").strip()
	if category not in FEEDBACK_CATEGORIES:
		frappe.throw(_("Select a valid feedback category."))
	if not flt(stars):
		frappe.throw(_("Give a rating between {0} and {1} stars.").format(RATING_STEP, RATING_MAX))
	return category, (comments or "").strip()


def submit_feedback(
	*,
	party: str,
	project: str,
	stars,
	customer: str | None = None,
	transporter: str | None = None,
	category: str | None = None,
	comments: str | None = None,
	would_recommend: bool | int = 0,
	containers=None,
	allowed_containers: list[str] | None = None,
) -> dict:
	"""Create or update the party's feedback on a shipment.

	Ownership must already be verified by the caller - this writes with
	`ignore_permissions` because portal users hold no role on the DocType.
	`allowed_containers` narrows what may be ticked (a transporter may only
	name the boxes on their own allocation).
	"""
	if party not in (PARTY_CUSTOMER, PARTY_TRANSPORTER):
		frappe.throw(_("Unknown feedback author."))
	if not project or not frappe.db.exists("Project", project):
		frappe.throw(_("Select the shipment this feedback is about."))

	category, comments = _validate_inputs(category, comments, stars)
	container_names = _clean_containers(containers, project, allowed_containers)

	user = frappe.session.user
	existing = frappe.db.get_value(
		FEEDBACK_DOCTYPE,
		{"project": project, "submitted_by_party": party, "submitted_by": user},
		"name",
	)

	values = {
		"project": project,
		"submitted_by_party": party,
		"customer": customer if party == PARTY_CUSTOMER else None,
		"transporter": transporter if party == PARTY_TRANSPORTER else None,
		"rating": rating_from_stars(stars),
		"category": category,
		"comments": comments,
		"would_recommend": 1 if cint(would_recommend) else 0,
		"submitted_on": now_datetime(),
	}

	if existing:
		doc = frappe.get_doc(FEEDBACK_DOCTYPE, existing)
		doc.update(values)
		# A revised rating deserves another look from ops.
		if doc.status == "Resolved":
			doc.status = "Acknowledged"
		updated = True
	else:
		doc = frappe.new_doc(FEEDBACK_DOCTYPE)
		doc.update(values)
		doc.submitted_by = user
		doc.status = "New"
		updated = False

	doc.set("containers", [])
	for name in container_names:
		doc.append("containers", {"container_tracker": name})

	doc.save(ignore_permissions=True) if existing else doc.insert(ignore_permissions=True)

	notify_feedback(doc)

	return {
		"ok": True,
		"name": doc.name,
		"updated": updated,
		"message": _("Thanks - your feedback has been updated.")
		if updated
		else _("Thanks - your feedback has been recorded."),
		"feedback": serialize_feedback(doc.as_dict()),
	}


def notify_feedback(doc) -> dict:
	try:
		return send_notification(PORTAL_FEEDBACK_NOTIFICATION, doc, audience="Operations")
	except Exception:
		frappe.log_error(title="Portal feedback notification failed", message=frappe.get_traceback())
		return {"notified": 0, "emails_sent": 0}


def _feedback_rows(filters: dict, limit: int = 50) -> list[dict]:
	if not frappe.db.exists("DocType", FEEDBACK_DOCTYPE):
		return []
	return frappe.get_all(
		FEEDBACK_DOCTYPE,
		filters=filters,
		fields=_FEEDBACK_FIELDS,
		order_by="submitted_on desc",
		limit_page_length=limit,
		ignore_permissions=True,
	)


def get_my_feedback(*, party: str, project: str, user: str | None = None) -> dict | None:
	"""The feedback the logged-in portal user left on this shipment, if any."""
	user = user or frappe.session.user
	if not user or user == "Guest" or not project:
		return None
	rows = _feedback_rows(
		{"project": project, "submitted_by_party": party, "submitted_by": user}, limit=1
	)
	return serialize_feedback(rows[0]) if rows else None


def get_feedback_for_project(project: str, *, party: str | None = None) -> list[dict]:
	if not project:
		return []
	filters: dict = {"project": project}
	if party:
		filters["submitted_by_party"] = party
	return [serialize_feedback(row) for row in _feedback_rows(filters)]


def feedback_summary(rows: list[dict] | None) -> dict:
	rows = rows or []
	if not rows:
		return {"count": 0, "average_stars": 0, "average_display": ""}
	total = sum(flt(r.get("stars")) for r in rows)
	average = total / len(rows)
	return {
		"count": len(rows),
		"average_stars": round(average, 1),
		"average_display": f"{average:.1f}/{RATING_MAX}",
	}


# ─── Desk endpoints ──────────────────────────────────────────────────────────
#
# Feedback is written by portal accounts but read and answered only in Desk.
# `_require_desk_access` refuses Website Users outright, so a portal role that
# happens to carry a DocPerm can never read another party's feedback.


def _require_desk_access(ptype: str = "read", doc: str | None = None) -> None:
	if is_portal_user():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	frappe.has_permission(FEEDBACK_DOCTYPE, ptype=ptype, doc=doc, throw=True)


@frappe.whitelist()
def respond_to_feedback(name: str, response: str, status: str | None = None) -> dict:
	"""Desk: record CGM's answer to a piece of portal feedback."""
	_require_desk_access(ptype="write", doc=name)
	response = (response or "").strip()
	if not response:
		frappe.throw(_("Enter a response."))
	if status and status not in FEEDBACK_STATUSES:
		frappe.throw(_("Unknown feedback status."))

	doc = frappe.get_doc(FEEDBACK_DOCTYPE, name)
	doc.response = response
	doc.status = status or "Acknowledged"
	doc.save()
	return {"ok": True, "name": doc.name, "message": _("Response saved.")}


@frappe.whitelist()
def get_project_feedback(project: str) -> dict:
	"""Desk: every party's feedback on a shipment, with the running average."""
	_require_desk_access()
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	rows = get_feedback_for_project(project)
	return {"rows": rows, "summary": feedback_summary(rows)}
