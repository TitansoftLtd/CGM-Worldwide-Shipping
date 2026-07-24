# Copyright (c) 2026, Titansoft Limited and contributors
"""Generic operational Update — transporter, customer, and internal sources."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	OPERATIONAL_UPDATE_NOTIFICATION,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
	_update_allocation_item_row,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import send_notification

UPDATE_DOCTYPE = "Update"

UPDATE_SOURCES = (
	"Transporter",
	"Customer",
	"Internal",
	"Customs",
	"Finance",
	"Other",
)

TRANSPORTER_SUBJECTS = (
	"En Route",
	"Delayed",
	"At Port Gate",
	"Delivered",
	"Offloaded",
	"Other",
)

_TRACKER_DATE_MAP = {
	"At Port Gate": "gate_out_date_port",
	"Delivered": "gate_in_date_warehouse",
	"Offloaded": "offloading_date",
}

_UPDATE_LIST_FIELDS = [
	"name",
	"update_source",
	"subject",
	"message",
	"posted_on",
	"posted_by",
	"is_read",
	"project",
	"customer",
	"container_tracker",
	"container_number",
	"transporter",
	"allocation",
	"attachment",
	"event_date",
	"truck_number",
	"driver_name",
	"driver_contact",
]


def _customer_for_project(project: str | None) -> str | None:
	if not project:
		return None
	return frappe.db.get_value("Project", project, "customer")


def serialize_update(doc) -> dict:
	customer = doc.get("customer")
	project = doc.get("project")
	posted_on = doc.get("posted_on")
	event_date = doc.get("event_date")
	return {
		"name": doc.name,
		"update_source": doc.update_source,
		"subject": doc.subject,
		"message": doc.message or "",
		"posted_on": str(posted_on) if posted_on else "",
		"posted_by": doc.posted_by,
		"posted_by_name": frappe.utils.get_fullname(doc.posted_by) if doc.posted_by else "",
		"is_read": cint(doc.get("is_read")),
		"project": project,
		"project_ref": _project_display_ref(project) if project else "",
		"customer": customer,
		"customer_name": (
			frappe.db.get_value("Customer", customer, "customer_name") or customer or ""
		),
		"container_tracker": doc.get("container_tracker") or "",
		"container_number": doc.get("container_number") or "",
		"transporter": doc.get("transporter") or "",
		"allocation": doc.get("allocation") or "",
		"attachment": doc.get("attachment") or "",
		"event_date": str(event_date) if event_date else "",
		"truck_number": doc.get("truck_number") or "",
		"driver_name": doc.get("driver_name") or "",
		"driver_contact": doc.get("driver_contact") or "",
		# Backward-compatible aliases used by older portal/ops UI.
		"update_type": doc.subject,
	}


def _project_display_ref(project_name: str) -> str:
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
		get_project_reference,
	)

	if not project_name or not frappe.db.exists("Project", project_name):
		return project_name or ""
	doc = frappe.get_doc("Project", project_name, ignore_permissions=True)
	return get_project_reference(doc) or doc.get("project_name") or project_name


def _resolve_allocation_links(
	*,
	allocation: str | None = None,
	allocation_item: str | None = None,
	container_tracker: str | None = None,
	project: str | None = None,
) -> tuple[str | None, str | None]:
	"""Link Update to the active Container Allocation when one exists."""
	if allocation:
		return allocation, allocation_item

	if container_tracker:
		row = frappe.db.sql(
			"""
			SELECT cai.parent AS allocation, cai.name AS allocation_item
			FROM `tabContainer Allocation Item` cai
			INNER JOIN `tabContainer Allocation` ca
				ON ca.name = cai.parent
			WHERE cai.container_tracker = %s
				AND ca.docstatus = 1
			ORDER BY ca.modified DESC
			LIMIT 1
			""",
			(container_tracker,),
			as_dict=True,
		)
		if row:
			return row[0].allocation, row[0].allocation_item or allocation_item

	if project:
		allocation_name = frappe.db.get_value(
			"Container Allocation",
			{"project": project, "docstatus": 1},
			"name",
			order_by="modified desc",
		)
		if allocation_name:
			return allocation_name, allocation_item

	return None, allocation_item


def create_update(
	*,
	update_source: str,
	subject: str,
	message: str = "",
	project: str | None = None,
	customer: str | None = None,
	container_tracker: str | None = None,
	container_number: str | None = None,
	transporter: str | None = None,
	allocation: str | None = None,
	allocation_item: str | None = None,
	event_date: str | None = None,
	attachment: str = "",
	truck_number: str = "",
	driver_name: str = "",
	driver_contact: str = "",
	related_doctype: str | None = None,
	related_name: str | None = None,
	notify: bool = True,
) -> dict:
	"""Create a generic Update record — single write path for all sources."""
	update_source = (update_source or "").strip()
	if update_source not in UPDATE_SOURCES:
		frappe.throw(_("Select a valid update source."))

	subject = (subject or "").strip()
	if not subject:
		frappe.throw(_("Subject is required."))

	if not customer and project:
		customer = _customer_for_project(project)

	if container_tracker and not container_number:
		container_number = frappe.db.get_value(
			"Container Tracker", container_tracker, "container_number"
		)

	allocation, allocation_item = _resolve_allocation_links(
		allocation=allocation,
		allocation_item=allocation_item,
		container_tracker=container_tracker,
		project=project,
	)

	doc = frappe.new_doc(UPDATE_DOCTYPE)
	doc.update_source = update_source
	doc.subject = subject
	doc.message = (message or "").strip()
	doc.project = project
	doc.customer = customer
	doc.container_tracker = container_tracker
	doc.container_number = container_number
	doc.transporter = transporter
	doc.allocation = allocation
	doc.allocation_item = allocation_item
	doc.event_date = getdate(event_date) if event_date else None
	doc.attachment = (attachment or "").strip() or None
	doc.truck_number = (truck_number or "").strip()
	doc.driver_name = (driver_name or "").strip()
	doc.driver_contact = (driver_contact or "").strip()
	doc.related_doctype = related_doctype
	doc.related_name = related_name
	doc.posted_on = now_datetime()
	doc.posted_by = frappe.session.user
	doc.is_read = 0
	doc.insert(ignore_permissions=True)

	if notify:
		notify_operations(doc)

	return {
		"ok": True,
		"name": doc.name,
		"message": _("Update posted."),
		"update": serialize_update(doc),
	}


def post_truck_update(
	allocation_name: str,
	item_name: str,
	update_type: str = "",
	message: str = "",
	event_date: str | None = None,
	attachment: str = "",
	truck_number: str = "",
	driver_name: str = "",
	driver_contact: str = "",
	subject: str = "",
	*,
	transporter: str | None = None,
) -> dict:
	"""Transporter portal entry point — creates an Update with source=Transporter."""
	subject = (subject or update_type or "").strip()
	if subject not in TRANSPORTER_SUBJECTS:
		frappe.throw(_("Select a valid subject."))

	allocation = frappe.get_doc("Container Allocation", allocation_name, ignore_permissions=True)
	if allocation.docstatus != 1:
		frappe.throw(_("This allocation is not active."), frappe.PermissionError)
	if transporter and allocation.transporter != transporter:
		frappe.throw(_("You do not have access to this allocation."), frappe.PermissionError)

	item = _get_allocation_item(allocation, item_name)
	message = (message or "").strip()

	if subject == "Truck Changed":
		frappe.throw(
			_(
				"Truck changes are handled by CGM. Ask CGM to reassign the container to another offered truck."
			)
		)
	elif subject in ("Delayed", "Other") and not message:
		frappe.throw(_("Please add a short message for this update."))

	result = create_update(
		update_source="Transporter",
		subject=subject,
		message=message,
		project=allocation.project,
		customer=_customer_for_project(allocation.project),
		container_tracker=item.container_tracker,
		container_number=item.container_number
		or frappe.db.get_value("Container Tracker", item.container_tracker, "container_number"),
		transporter=allocation.transporter,
		allocation=allocation_name,
		allocation_item=item_name,
		event_date=event_date,
		attachment=attachment,
		truck_number=truck_number,
		driver_name=driver_name,
		driver_contact=driver_contact,
		related_doctype="Container Allocation",
		related_name=allocation_name,
		notify=True,
	)

	doc = frappe.get_doc(UPDATE_DOCTYPE, result["name"], ignore_permissions=True)
	_apply_transporter_side_effects(doc, item_name)
	result["message"] = _("Truck update posted.")
	return result


def post_customer_update(
	project: str,
	subject: str,
	message: str,
	*,
	customer: str | None = None,
) -> dict:
	"""Customer portal entry point — creates an Update with source=Customer."""
	subject = (subject or "").strip()
	message = (message or "").strip()
	if not subject:
		frappe.throw(_("Subject is required."))
	if not message:
		frappe.throw(_("Please enter a message."))
	if not project or not frappe.db.exists("Project", project):
		frappe.throw(_("Shipment not found."), frappe.DoesNotExistError)

	project_customer = _customer_for_project(project)
	if customer and project_customer and customer != project_customer:
		frappe.throw(_("You do not have access to this shipment."), frappe.PermissionError)

	return create_update(
		update_source="Customer",
		subject=subject,
		message=message,
		project=project,
		customer=customer or project_customer,
		related_doctype="Project",
		related_name=project,
		notify=True,
	)


def _get_allocation_item(allocation, item_name: str):
	for row in allocation.containers or []:
		if row.name == item_name:
			return row
	frappe.throw(_("Container allocation row not found."), frappe.DoesNotExistError)


def _apply_transporter_side_effects(doc, item_name: str) -> None:
	if doc.subject == "Truck Changed":
		_apply_truck_change(doc, item_name)
	if doc.event_date and doc.container_tracker:
		_apply_tracker_date(doc)


def _apply_truck_change(doc, item_name: str) -> None:
	values = {"truck_number": doc.truck_number}
	if doc.driver_name:
		values["driver_name"] = doc.driver_name
	if doc.driver_contact:
		values["driver_contact"] = doc.driver_contact
	_update_allocation_item_row(item_name, values)

	if not doc.container_tracker:
		return
	frappe.db.set_value(
		"Container Tracker",
		doc.container_tracker,
		values,
		update_modified=True,
	)
	frappe.clear_document_cache("Container Tracker", doc.container_tracker)


def _apply_tracker_date(doc) -> None:
	fieldname = _TRACKER_DATE_MAP.get(doc.subject)
	if not fieldname:
		return
	current = frappe.db.get_value("Container Tracker", doc.container_tracker, fieldname)
	if current:
		return
	frappe.db.set_value(
		"Container Tracker",
		doc.container_tracker,
		{fieldname: doc.event_date},
		update_modified=True,
	)
	frappe.clear_document_cache("Container Tracker", doc.container_tracker)


def notify_operations(doc) -> dict:
	return send_notification(OPERATIONAL_UPDATE_NOTIFICATION, doc, audience="Operations")


def get_updates_for_allocation_item(
	item_name: str,
	limit: int = 50,
	*,
	container_tracker: str | None = None,
) -> list[dict]:
	"""Updates for one allocation row (by item and/or container tracker)."""
	if not item_name and not container_tracker:
		return []
	if not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return []

	or_filters: list[list] = []
	if item_name:
		or_filters.append(["allocation_item", "=", item_name])
	if container_tracker:
		or_filters.append(["container_tracker", "=", container_tracker])

	rows = frappe.get_all(
		UPDATE_DOCTYPE,
		or_filters=or_filters,
		fields=_UPDATE_LIST_FIELDS,
		order_by="posted_on desc",
		limit_page_length=limit,
		ignore_permissions=True,
	)
	seen: set[str] = set()
	result: list[dict] = []
	for row in rows:
		if row.name in seen:
			continue
		seen.add(row.name)
		result.append(serialize_update(frappe._dict(row)))
	return result


def _preview_message(message: str, max_len: int = 180) -> str:
	text = (message or "").strip()
	if not text:
		return ""
	lines = [ln for ln in text.splitlines() if ln.strip()][:3]
	joined = " ".join(lines)
	if len(joined) > max_len or len([ln for ln in text.splitlines() if ln.strip()]) > 3:
		return joined[:max_len].rstrip() + "…"
	return joined


def render_updates_list_html(rows: list[dict] | None, *, show_source: bool = False) -> str:
	"""Ops-board style update cards for portal/server templates (same CSS as Desk)."""
	from frappe.utils import escape_html, pretty_date

	rows = rows or []
	if not rows:
		return ""

	source_class = {
		"Customer": "blue",
		"Transporter": "orange",
		"Internal": "gray",
		"Customs": "cyan",
		"Finance": "yellow",
		"Other": "gray",
	}

	cards: list[str] = []
	for row in rows:
		subject = escape_html(row.get("subject") or row.get("update_type") or _("Update"))
		source = (row.get("update_source") or "").strip() if show_source else ""
		source_pill = (
			f'<span class="indicator-pill {source_class.get(source, "gray")} no-indicator-dot cgm-upd-source">'
			f"{escape_html(source.upper())}</span>"
			if source
			else ""
		)
		when = ""
		if row.get("posted_on"):
			try:
				when = escape_html(pretty_date(row["posted_on"]))
			except Exception:
				when = escape_html(str(row["posted_on"]))

		meta_bits = []
		shipment = row.get("project_ref") or row.get("project")
		if shipment:
			meta_bits.append(
				f'<div class="cgm-updates-meta-line">'
				f'<span class="cgm-updates-meta-label">{escape_html(_("Shipment"))}:</span> '
				f'<span class="cgm-updates-meta-value">{escape_html(shipment)}</span></div>'
			)
		customer = row.get("customer_name") or row.get("customer")
		if customer:
			meta_bits.append(
				f'<div class="cgm-updates-meta-line">'
				f'<span class="cgm-updates-meta-label">{escape_html(_("Customer"))}:</span> '
				f'<span class="cgm-updates-meta-value">{escape_html(customer)}</span></div>'
			)
		if row.get("container_number"):
			meta_bits.append(
				f'<div class="cgm-updates-meta-line">'
				f'<span class="cgm-updates-meta-label">{escape_html(_("Container"))}:</span> '
				f'<span class="cgm-updates-meta-value">{escape_html(row["container_number"])}</span></div>'
			)
		meta_html = f'<div class="cgm-updates-meta">{"".join(meta_bits)}</div>' if meta_bits else ""

		preview = _preview_message(row.get("message") or "")
		preview_html = (
			f'<div class="cgm-updates-preview">{escape_html(preview)}</div>' if preview else ""
		)
		name = escape_html(row.get("name") or "")
		unread = "" if cint(row.get("is_read")) else " is-unread"
		when_html = (
			f'<span class="cgm-updates-when text-muted small">{when}</span>' if when else ""
		)

		cards.append(
			f'<div class="list-row-container{unread}" data-update="{name}">'
			f'<div class="cgm-updates-head">'
			f'<div class="cgm-updates-badges">'
			f'<span class="indicator-pill red no-indicator-dot cgm-upd-subject">{subject}</span>'
			f"{source_pill}"
			f"</div>"
			f"{when_html}"
			f"</div>"
			f'<div class="cgm-updates-body">'
			f'<div class="list-row-left">{meta_html}{preview_html}</div>'
			f'<div class="list-row-right">'
			f'<button type="button" class="btn btn-xs btn-default cgm-upd-view-more" data-update="{name}">'
			f'{escape_html(_("View More"))}</button>'
			f"</div></div></div>"
		)

	return f'<div class="cgm-updates-list">{"".join(cards)}</div>'



def get_updates_for_container_tracker(container_tracker: str, limit: int = 50) -> list[dict]:
	if not container_tracker or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return []
	rows = frappe.get_all(
		UPDATE_DOCTYPE,
		filters={"container_tracker": container_tracker},
		fields=_UPDATE_LIST_FIELDS,
		order_by="posted_on desc",
		limit_page_length=limit,
		ignore_permissions=True,
	)
	return [serialize_update(frappe._dict(row)) for row in rows]


def get_updates_for_project(project: str, limit: int = 100) -> list[dict]:
	if not project or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return []
	rows = frappe.get_all(
		UPDATE_DOCTYPE,
		filters={"project": project},
		fields=_UPDATE_LIST_FIELDS,
		order_by="posted_on desc",
		limit_page_length=limit,
		ignore_permissions=True,
	)
	return [serialize_update(frappe._dict(row)) for row in rows]


def get_my_updates_for_project(project: str, limit: int = 100) -> list[dict]:
	"""Updates posted by the current user on a shipment (customer portal)."""
	if not project or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return []
	user = frappe.session.user
	if not user or user == "Guest":
		return []
	rows = frappe.get_all(
		UPDATE_DOCTYPE,
		filters={"project": project, "posted_by": user},
		fields=_UPDATE_LIST_FIELDS,
		order_by="posted_on desc",
		limit_page_length=limit,
		ignore_permissions=True,
	)
	return [serialize_update(frappe._dict(row)) for row in rows]


def get_my_updates_for_allocation(allocation_name: str, limit: int = 100) -> list[dict]:
	"""Updates posted by the current user on an allocation (transporter portal)."""
	if not allocation_name or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return []
	user = frappe.session.user
	if not user or user == "Guest":
		return []
	rows = frappe.get_all(
		UPDATE_DOCTYPE,
		filters={"allocation": allocation_name, "posted_by": user},
		fields=_UPDATE_LIST_FIELDS,
		order_by="posted_on desc",
		limit_page_length=limit,
		ignore_permissions=True,
	)
	return [serialize_update(frappe._dict(row)) for row in rows]


def get_latest_updates_for_trackers(tracker_names: list[str]) -> dict[str, dict]:
	if not tracker_names or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return {}

	placeholders = ", ".join(["%s"] * len(tracker_names))
	rows = frappe.db.sql(
		f"""
		SELECT
			t.container_tracker,
			t.subject AS update_type,
			t.subject,
			t.message,
			t.posted_on,
			t.event_date,
			t.update_source
		FROM `tabUpdate` t
		INNER JOIN (
			SELECT container_tracker, MAX(posted_on) AS max_posted
			FROM `tabUpdate`
			WHERE container_tracker IN ({placeholders})
			GROUP BY container_tracker
		) latest
			ON latest.container_tracker = t.container_tracker
			AND latest.max_posted = t.posted_on
		""",
		tuple(tracker_names),
		as_dict=True,
	)
	return {row.container_tracker: row for row in rows}


def format_latest_update_summary(update: dict | None) -> str:
	if not update:
		return ""
	parts = [update.get("subject") or update.get("update_type") or ""]
	if update.get("message"):
		parts.append(update["message"])
	label = " — ".join(p for p in parts if p)
	posted = update.get("posted_on")
	if posted:
		formatted = frappe.format(posted, {"fieldtype": "Datetime"})
		label = f"{label} ({formatted})"
	return label


@frappe.whitelist()
def get_allocation_truck_updates(allocation_name: str) -> list[dict]:
	"""Updates linked to this allocation, its containers, or its shipment."""
	frappe.has_permission("Container Allocation", ptype="read", doc=allocation_name, throw=True)
	if not allocation_name or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return []

	allocation = frappe.db.get_value(
		"Container Allocation",
		allocation_name,
		["name", "project"],
		as_dict=True,
	)
	if not allocation:
		return []

	tracker_names = frappe.get_all(
		"Container Allocation Item",
		filters={"parent": allocation_name, "parenttype": "Container Allocation"},
		pluck="container_tracker",
		ignore_permissions=True,
	)
	tracker_names = [t for t in tracker_names if t]

	or_filters: list[list] = [["allocation", "=", allocation_name]]
	if tracker_names:
		or_filters.append(["container_tracker", "in", tracker_names])
	if allocation.project:
		or_filters.append(["project", "=", allocation.project])

	rows = frappe.get_all(
		UPDATE_DOCTYPE,
		or_filters=or_filters,
		fields=_UPDATE_LIST_FIELDS,
		order_by="posted_on desc",
		limit_page_length=200,
		ignore_permissions=True,
	)

	seen: set[str] = set()
	result: list[dict] = []
	for row in rows:
		if row.name in seen:
			continue
		seen.add(row.name)
		result.append(serialize_update(frappe._dict(row)))
	return result


@frappe.whitelist()
def get_tracker_truck_updates(container_tracker: str) -> list[dict]:
	frappe.has_permission("Container Tracker", ptype="read", doc=container_tracker, throw=True)
	return get_updates_for_container_tracker(container_tracker)


@frappe.whitelist()
def get_project_updates(project: str) -> list[dict]:
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	return get_updates_for_project(project)


@frappe.whitelist()
def get_ops_updates(filters=None) -> dict:
	"""Paginated updates feed for the Container Ops Board Updates tab."""
	frappe.has_permission(UPDATE_DOCTYPE, ptype="read", throw=True)
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) if filters else {}
	filters = frappe._dict(filters or {})

	query_filters: dict = {}
	source = filters.get("update_source")
	if source:
		if isinstance(source, (list, tuple)):
			query_filters["update_source"] = ("in", list(source))
		else:
			query_filters["update_source"] = source
	else:
		# Default ops feed: transporter + customer (extensible later).
		query_filters["update_source"] = ("in", ["Transporter", "Customer"])

	if filters.get("customer"):
		query_filters["customer"] = filters.customer
	if filters.get("project"):
		query_filters["project"] = filters.project
	if filters.get("container_tracker"):
		query_filters["container_tracker"] = filters.container_tracker
	if filters.get("transporter"):
		query_filters["transporter"] = filters.transporter

	subject = (filters.get("subject") or filters.get("update_type") or "").strip()
	if subject:
		query_filters["subject"] = subject

	# Status on the Updates tab maps to unread/read (is_read), not container status.
	status = (filters.get("status") or "").strip()
	if status in ("Unread", "unread"):
		query_filters["is_read"] = 0
	elif status in ("Read", "read"):
		query_filters["is_read"] = 1
	elif filters.get("is_read") in (0, 1, "0", "1"):
		query_filters["is_read"] = cint(filters.is_read)

	posted_from = filters.get("date_from") or filters.get("posted_from")
	posted_to = filters.get("date_to") or filters.get("posted_to")
	if posted_from and posted_to:
		query_filters["posted_on"] = (
			"between",
			[getdate(posted_from), get_datetime(f"{getdate(posted_to)} 23:59:59")],
		)
	elif posted_from:
		query_filters["posted_on"] = (">=", getdate(posted_from))
	elif posted_to:
		query_filters["posted_on"] = ("<=", get_datetime(f"{getdate(posted_to)} 23:59:59"))

	try:
		start = max(0, int(filters.get("start") or 0))
	except (TypeError, ValueError):
		start = 0
	try:
		page_length = min(max(int(filters.get("page_length") or 20), 1), 200)
	except (TypeError, ValueError):
		page_length = 20

	total_count = frappe.db.count(UPDATE_DOCTYPE, query_filters)
	unread_count = frappe.db.count(
		UPDATE_DOCTYPE,
		{
			**{k: v for k, v in query_filters.items() if k != "is_read"},
			"is_read": 0,
		},
	)
	rows = frappe.get_all(
		UPDATE_DOCTYPE,
		filters=query_filters,
		fields=_UPDATE_LIST_FIELDS,
		order_by="posted_on desc",
		limit_start=start,
		limit_page_length=page_length,
	)
	return {
		"rows": [serialize_update(frappe._dict(row)) for row in rows],
		"total_count": total_count,
		"unread_count": unread_count,
		"start": start,
		"page_length": page_length,
	}


@frappe.whitelist()
def get_unread_update_count() -> int:
	frappe.has_permission(UPDATE_DOCTYPE, ptype="read", throw=True)
	return frappe.db.count(
		UPDATE_DOCTYPE,
		{"is_read": 0, "update_source": ("in", ["Transporter", "Customer"])},
	)


@frappe.whitelist()
def mark_update_read(name: str) -> dict:
	if not frappe.has_permission(UPDATE_DOCTYPE, ptype="write", doc=name):
		# Still allow ops users with read access to clear the badge.
		if not frappe.has_permission(UPDATE_DOCTYPE, ptype="read", doc=name):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		frappe.db.set_value(UPDATE_DOCTYPE, name, "is_read", 1, update_modified=False)
		return {"ok": True, "name": name, "is_read": 1}
	frappe.db.set_value(UPDATE_DOCTYPE, name, "is_read", 1, update_modified=False)
	return {"ok": True, "name": name, "is_read": 1}


def _detail_field(
	fieldname: str,
	label: str,
	fieldtype: str,
	value,
	*,
	options: str | None = None,
	portal: bool = False,
) -> dict | None:
	if value is None or value == "":
		return None

	display = value
	out_type = fieldtype
	out_options = options

	# Portal Dialog must not use Link/Date/Datetime/Attach controls — website users
	# lack DocType permissions and date parsers differ from Desk.
	if portal:
		if fieldtype in ("Date", "Datetime"):
			try:
				display = frappe.format(value, {"fieldtype": fieldtype})
			except Exception:
				display = str(value)
			out_type = "Data"
			out_options = None
		elif fieldtype in ("Link", "Dynamic Link"):
			if options == "User":
				display = frappe.utils.get_fullname(value) or value
			elif options == "Customer":
				display = frappe.db.get_value("Customer", value, "customer_name") or value
			elif options == "Supplier":
				display = frappe.db.get_value("Supplier", value, "supplier_name") or value
			elif options == "Project":
				display = _project_display_ref(value) or value
			elif options == "Container Tracker":
				display = (
					frappe.db.get_value("Container Tracker", value, "container_number") or value
				)
			out_type = "Data"
			out_options = None
		elif fieldtype == "Attach":
			out_type = "Data"
			out_options = None
		else:
			out_options = None

	return {
		"fieldname": fieldname,
		"label": label,
		"fieldtype": out_type,
		"value": display,
		**({"options": out_options} if out_options else {}),
	}


def _column_break(fieldname: str) -> dict:
	return {"fieldtype": "Column Break", "fieldname": fieldname}


def _build_update_detail_sections(
	doc, *, include_source: bool = True, portal: bool = False
) -> list[dict]:
	"""Data-driven dialog sections — only fields with values, source-aware."""
	sections: list[dict] = []

	general_parts = [
		_detail_field("subject", _("Subject"), "Data", doc.subject, portal=portal)
	]
	if include_source:
		general_parts.append(
			_detail_field(
				"update_source",
				_("Update Source"),
				"Data",
				doc.update_source,
				portal=portal,
			)
		)
	general_fields = [f for f in general_parts if f]
	if general_fields:
		general_fields.append(_column_break("column_break_general"))
		for f in (
			_detail_field(
				"posted_by",
				_("Posted By"),
				"Link",
				doc.posted_by,
				options="User",
				portal=portal,
			),
			_detail_field(
				"posted_on",
				_("Posted On"),
				"Datetime",
				doc.posted_on,
				portal=portal,
			),
		):
			if f:
				general_fields.append(f)
		sections.append({"label": _("General Information"), "fields": general_fields})

	reference_fields = []
	if doc.project:
		reference_fields.append(
			_detail_field(
				"project",
				_("Shipment"),
				"Link",
				doc.project,
				options="Project",
				portal=portal,
			)
		)
	if doc.customer and not portal:
		# Customer is desk-facing; transporter portal does not need it.
		reference_fields.append(
			_detail_field(
				"customer",
				_("Customer"),
				"Link",
				doc.customer,
				options="Customer",
				portal=portal,
			)
		)
	if doc.container_number:
		reference_fields.append(
			_detail_field(
				"container_number",
				_("Container"),
				"Data",
				doc.container_number,
				portal=portal,
			)
		)
	elif doc.container_tracker:
		reference_fields.append(
			_detail_field(
				"container_tracker",
				_("Container"),
				"Link",
				doc.container_tracker,
				options="Container Tracker",
				portal=portal,
			)
		)
	if doc.allocation and not portal:
		reference_fields.append(
			_detail_field(
				"allocation",
				_("Container Allocation"),
				"Link",
				doc.allocation,
				options="Container Allocation",
				portal=portal,
			)
		)
	if reference_fields:
		if len(reference_fields) > 2:
			mid = (len(reference_fields) + 1) // 2
			reference_fields = (
				reference_fields[:mid]
				+ [_column_break("column_break_references")]
				+ reference_fields[mid:]
			)
		sections.append({"label": _("References"), "fields": reference_fields})

	if doc.update_source == "Transporter":
		transport_fields = [
			f
			for f in (
				_detail_field(
					"transporter",
					_("Transporter"),
					"Link",
					doc.transporter,
					options="Supplier",
					portal=portal,
				)
				if not portal
				else None,
				_detail_field(
					"truck_number", _("Truck Number"), "Data", doc.truck_number, portal=portal
				),
				_detail_field(
					"driver_name", _("Driver Name"), "Data", doc.driver_name, portal=portal
				),
				_detail_field(
					"driver_contact",
					_("Driver Contact"),
					"Data",
					doc.driver_contact,
					portal=portal,
				),
				_detail_field(
					"event_date", _("Event Date"), "Date", doc.event_date, portal=portal
				),
			)
			if f
		]
		if transport_fields:
			if len(transport_fields) > 2:
				mid = (len(transport_fields) + 1) // 2
				transport_fields = (
					transport_fields[:mid]
					+ [_column_break("column_break_transport")]
					+ transport_fields[mid:]
				)
			sections.append({"label": _("Transport Details"), "fields": transport_fields})

	message_fields = [
		f
		for f in (
			_detail_field(
				"message", _("Message"), "Small Text", doc.message, portal=portal
			),
			_detail_field(
				"attachment", _("Attachment"), "Attach", doc.attachment, portal=portal
			),
		)
		if f
	]
	if message_fields:
		sections.append({"label": "", "fields": message_fields})

	return sections


def _transporter_can_access_update(doc) -> bool:
	"""Allow transporter portal users to view updates on their allocations."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_portal import (
		get_transporter_for_user,
	)

	transporter = get_transporter_for_user()
	if not transporter:
		return False
	if doc.get("transporter") == transporter:
		return True
	allocation = doc.get("allocation")
	if allocation:
		return frappe.db.get_value("Container Allocation", allocation, "transporter") == transporter
	return False


def _customer_can_access_update(doc) -> bool:
	"""Allow customer portal users to view updates on their shipments."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.portal import (
		customer_for_user,
		get_shipment_for_customer,
	)

	customer = customer_for_user(frappe.session.user)
	if not customer:
		return False
	if doc.get("customer") == customer:
		return True
	project = doc.get("project")
	if project and get_shipment_for_customer(project, customer):
		return True
	return False


@frappe.whitelist()
def get_update_detail(name: str, include_source: int | str | None = 1) -> dict:
	"""Return labeled detail sections for View More (Desk + portals).

	Portal users have no Update DocType role — authorize via transporter/customer
	ownership and never run desk has_permission checks (those msgprint denials).
	"""
	doc = frappe.get_doc(UPDATE_DOCTYPE, name, check_permission=False)
	transporter_ok = _transporter_can_access_update(doc)
	customer_ok = _customer_can_access_update(doc)
	portal = bool(transporter_ok or customer_ok)

	if not portal:
		# Desk: require Update read. clear_messages — nested role checks may msgprint denials.
		can_read = frappe.has_permission(UPDATE_DOCTYPE, ptype="read", doc=name)
		frappe.clear_messages()
		if not can_read:
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		if not cint(doc.is_read):
			frappe.db.set_value(UPDATE_DOCTYPE, name, "is_read", 1, update_modified=False)
			doc.is_read = 1

	show_source = bool(cint(include_source if include_source is not None else 1)) and not portal
	payload = serialize_update(doc)
	payload["sections"] = _build_update_detail_sections(
		doc, include_source=show_source, portal=portal or not show_source
	)
	return payload



