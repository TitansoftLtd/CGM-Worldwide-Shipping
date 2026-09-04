# Copyright (c) 2026, Titansoft Limited and contributors
"""Generic operational Update — transporter, customer, and internal sources."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
	OPERATIONAL_UPDATE_NOTIFICATION,
	PORTAL_UPDATE_PUBLISHED_NOTIFICATION,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
	_update_allocation_item_row,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.notifications import (
	send_notification,
	send_notification_to,
)

UPDATE_DOCTYPE = "Shipment Update"

# Who wrote a message. Customs / Finance / Other were carried over from the
# original DocType and no code path ever produced them, so a filter on them
# always came back empty.
UPDATE_SOURCES = (
	"Customer",
	"Transporter",
	"Internal",
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
	"allocation_item",
	"attachment",
	"event_date",
	"truck_number",
	"driver_name",
	"driver_contact",
	"visible_to_customer",
	"visible_to_transporter",
	"parent_update",
	"customer_read_on",
	"transporter_read_on",
	"last_activity_on",
	"response_status",
	"responded_by",
	"responded_on",
	"response_update",
	"closed_by",
	"closed_on",
]

# Sources that represent CGM speaking to a portal party (as opposed to the
# party speaking to CGM). Used to work out which side of a thread a message
# sits on, and which audience flags may be set on it.
CGM_SOURCES = ("Internal",)

# The two portal parties. A message from either is a question CGM owes an
# answer to, which is what `response_status` on those rows tracks.
PARTY_SOURCES = ("Customer", "Transporter")

# A thread's life: CGM owes an answer, has given one, or the party has said the
# matter is settled. Only the party closes and reopens - it is their question.
STATUS_OPEN = "Open"
STATUS_ANSWERED = "Answered"
STATUS_CLOSED = "Closed"

# Subjects offered to CGM staff when publishing an update to a portal party.
PUBLISHED_SUBJECTS = (
	"Shipment Update",
	"Documents",
	"Customs & Clearance",
	"Container Update",
	"Transport & Delivery",
	"Finance",
	"Reply",
	"Other",
)

AUDIENCE_CUSTOMER = "customer"
AUDIENCE_TRANSPORTER = "transporter"


def default_audience_for_source(update_source: str) -> tuple[bool, bool]:
	"""Which portals an update reaches when the caller does not say.

	A party's own message is always visible to that party; CGM-authored
	updates stay internal unless the caller explicitly publishes them.
	"""
	return update_source == "Customer", update_source == "Transporter"


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
		"allocation_item": doc.get("allocation_item") or "",
		"parent_update": doc.get("parent_update") or "",
		"visible_to_customer": cint(doc.get("visible_to_customer")),
		"visible_to_transporter": cint(doc.get("visible_to_transporter")),
		"customer_read_on": str(doc.get("customer_read_on") or "") or "",
		"transporter_read_on": str(doc.get("transporter_read_on") or "") or "",
		"response_status": doc.get("response_status") or "",
		"responded_by": doc.get("responded_by") or "",
		"responded_by_name": (
			frappe.utils.get_fullname(doc.get("responded_by")) if doc.get("responded_by") else ""
		),
		"responded_on": str(doc.get("responded_on") or "") or "",
		"response_update": doc.get("response_update") or "",
		"closed_by": doc.get("closed_by") or "",
		"closed_by_name": (
			frappe.utils.get_fullname(doc.get("closed_by")) if doc.get("closed_by") else ""
		),
		"closed_on": str(doc.get("closed_on") or "") or "",
		"is_closed": doc.get("response_status") == STATUS_CLOSED,
		"last_activity_on": str(doc.get("last_activity_on") or doc.get("posted_on") or "") or "",
		# True when a party raised this and CGM has not answered it yet.
		"awaiting_response": (
			doc.update_source in PARTY_SOURCES
			and doc.get("response_status") not in (STATUS_ANSWERED, STATUS_CLOSED)
		),
		# True when CGM posted the update, False when the portal party did.
		"from_cgm": doc.update_source in CGM_SOURCES,
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
	visible_to_customer: bool | None = None,
	visible_to_transporter: bool | None = None,
	parent_update: str | None = None,
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

	# A reply inherits the party it is addressed to. Without a project there is
	# nothing else to derive it from, and an unscoped reply would drop out of
	# the customer's thread and out of the notification recipients.
	if parent_update and not (customer and transporter):
		parent = frappe.db.get_value(
			UPDATE_DOCTYPE, parent_update, ["customer", "transporter"], as_dict=True
		)
		if parent:
			customer = customer or parent.customer
			transporter = transporter or parent.transporter

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
	default_customer, default_transporter = default_audience_for_source(update_source)
	if visible_to_customer is None:
		visible_to_customer = default_customer
	if visible_to_transporter is None:
		visible_to_transporter = default_transporter
	doc.visible_to_customer = 1 if visible_to_customer else 0
	doc.visible_to_transporter = 1 if visible_to_transporter else 0
	doc.parent_update = parent_update or None
	# A message from a portal party is a question until CGM answers it; CGM's
	# own updates carry no response state.
	doc.response_status = "Open" if update_source in PARTY_SOURCES else None
	doc.posted_on = now_datetime()
	doc.last_activity_on = doc.posted_on
	doc.posted_by = frappe.session.user
	doc.is_read = 0
	doc.insert(ignore_permissions=True)

	# A reply is the thread's newest message, so the question it hangs off has
	# to move with it - that is what orders the ops feed.
	if doc.parent_update:
		values = {"last_activity_on": doc.posted_on}
		if doc.update_source in PARTY_SOURCES:
			# The party came back, so the thread needs an answer again - this is
			# also how a closed thread reopens. Who first responded is left
			# alone; that history still stands.
			values["response_status"] = STATUS_OPEN
			values["is_read"] = 0
			values["closed_by"] = None
			values["closed_on"] = None
		frappe.db.set_value(
			UPDATE_DOCTYPE, doc.parent_update, values, update_modified=False
		)

	if notify:
		if doc.update_source in CGM_SOURCES and (
			doc.visible_to_customer or doc.visible_to_transporter
		):
			notify_portal_audience(doc)
		else:
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
	container_tracker: str | None = None,
	parent_update: str | None = None,
	attachment: str = "",
) -> dict:
	"""Customer portal entry point — creates an Update with source=Customer.

	`project` may be empty: a general enquiry is a conversation with operations
	that is not about any one shipment. A message continuing a conversation
	needs no subject - it inherits the one it is answering.
	"""
	subject = (subject or "").strip()
	message = (message or "").strip()
	if not message:
		frappe.throw(_("Please enter a message."))

	parent_update = _validated_parent(parent_update, project=project)
	if not subject:
		if not parent_update:
			frappe.throw(_("Give this message a subject so operations can pick it up."))
		subject = _reply_subject(parent_update)

	if project and not frappe.db.exists("Project", project):
		frappe.throw(_("Shipment not found."), frappe.DoesNotExistError)

	project_customer = _customer_for_project(project) if project else None
	if customer and project_customer and customer != project_customer:
		frappe.throw(_("You do not have access to this shipment."), frappe.PermissionError)

	if container_tracker:
		tracker_project = frappe.db.get_value("Container Tracker", container_tracker, "project")
		if tracker_project != project:
			frappe.throw(_("This container is not on that shipment."), frappe.PermissionError)

	return create_update(
		update_source="Customer",
		subject=subject,
		message=message,
		project=project,
		customer=customer or project_customer,
		container_tracker=container_tracker,
		attachment=attachment,
		visible_to_customer=True,
		parent_update=parent_update,
		notify=True,
	)


def derive_subject(message: str) -> str:
	"""A subject taken from the message itself.

	A record created by hand in Desk skips the portal's subject field, and a
	blank subject reads as nothing in every feed - so the first line of the
	message stands in. Portal messages set their own: the first one asks for a
	subject, and replies inherit it.
	"""
	for line in (message or "").splitlines():
		line = line.strip()
		if line:
			return line if len(line) <= 80 else line[:79].rstrip() + "…"
	return _("Message")


def _reply_subject(parent_update: str) -> str:
	"""`Re: <original>`, without stacking `Re: Re: Re:` down a long thread."""
	parent = frappe.db.get_value(UPDATE_DOCTYPE, parent_update, "subject")
	subject = (parent or "").strip() or _("Message")
	if subject.lower().startswith("re:"):
		return subject
	return _("Re: {0}").format(subject)


def _validated_parent(parent_update: str | None, *, project: str | None = None) -> str | None:
	"""Only allow threading onto an Update that sits on the same shipment."""
	parent_update = (parent_update or "").strip()
	if not parent_update:
		return None
	parent = frappe.db.get_value(
		UPDATE_DOCTYPE, parent_update, ["name", "project"], as_dict=True
	)
	if not parent:
		return None
	if project and parent.project and parent.project != project:
		return None
	return parent.name


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


def is_portal_user(user: str | None = None) -> bool:
	"""True for a Website User - a customer or transporter portal account."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return True
	return frappe.db.get_value("User", user, "user_type") == "Website User"


def require_desk_access(ptype: str = "read", doc: str | None = None) -> None:
	"""Gate for the Desk-side Update endpoints.

	Role permissions alone are not enough here. Sites hand the Customer /
	Transporter roles a DocPerm on Update so staff who also hold those roles
	can work the ops board, which would otherwise let a portal account read
	another party's updates - or post one as CGM. Portal accounts are Website
	Users and belong on the portal-scoped APIs, so they are refused outright.
	"""
	if is_portal_user():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	frappe.has_permission(UPDATE_DOCTYPE, ptype=ptype, doc=doc, throw=True)


def notify_operations(doc) -> dict:
	return send_notification(OPERATIONAL_UPDATE_NOTIFICATION, doc, audience="Operations")


def notify_portal_audience(doc) -> dict:
	"""Email the customer and/or transporter when CGM publishes an update to them."""
	recipients = portal_recipients_for_update(doc)
	if not recipients:
		return {"notified": 0, "emails_sent": 0}
	return send_notification_to(
		PORTAL_UPDATE_PUBLISHED_NOTIFICATION,
		doc,
		recipients,
		audience="Portal",
	)


def portal_recipients_for_update(doc) -> list[str]:
	"""Portal user emails that should be told about this published update."""
	emails: list[str] = []
	if cint(doc.get("visible_to_customer")) and doc.get("customer"):
		emails.extend(_portal_user_emails("Customer", doc.get("customer")))
	if cint(doc.get("visible_to_transporter")):
		transporter = doc.get("transporter")
		if not transporter and doc.get("allocation"):
			transporter = frappe.db.get_value(
				"Container Allocation", doc.get("allocation"), "transporter"
			)
		if transporter:
			emails.extend(_portal_user_emails("Supplier", transporter))
	seen: set[str] = set()
	ordered: list[str] = []
	for email in emails:
		if email and email not in seen:
			seen.add(email)
			ordered.append(email)
	return ordered


def _portal_user_emails(parenttype: str, parent: str) -> list[str]:
	if not parent:
		return []
	users = frappe.get_all(
		"Portal User",
		filters={"parenttype": parenttype, "parent": parent},
		pluck="user",
		ignore_permissions=True,
	)
	enabled = []
	for user in users:
		if not user or user == "Guest":
			continue
		if frappe.db.get_value("User", user, "enabled"):
			enabled.append(user)
	return enabled


def post_transporter_message(
	*,
	transporter: str,
	subject: str,
	message: str,
	allocation: str | None = None,
	allocation_item: str | None = None,
	container_tracker: str | None = None,
	project: str | None = None,
	parent_update: str | None = None,
	attachment: str = "",
) -> dict:
	"""Transporter portal free-text message to CGM (not a structured truck event)."""
	subject = (subject or "").strip()
	message = (message or "").strip()
	if not message:
		frappe.throw(_("Please enter a message."))

	parent_update = _validated_parent(parent_update, project=project)
	if not subject:
		if not parent_update:
			frappe.throw(_("Give this message a subject so CGM can pick it up."))
		subject = _reply_subject(parent_update)

	return create_update(
		update_source="Transporter",
		subject=subject,
		message=message,
		project=project,
		container_tracker=container_tracker,
		transporter=transporter,
		allocation=allocation,
		allocation_item=allocation_item,
		attachment=attachment,
		visible_to_transporter=True,
		parent_update=parent_update,
		notify=True,
	)


def post_published_update(
	*,
	subject: str,
	message: str,
	project: str | None = None,
	container_tracker: str | None = None,
	to_customer: bool = False,
	to_transporter: bool = False,
	update_source: str = "Internal",
	transporter: str | None = None,
	allocation: str | None = None,
	parent_update: str | None = None,
	attachment: str = "",
	event_date: str | None = None,
) -> dict:
	"""CGM publishes an update to the customer and/or transporter portal."""
	subject = (subject or "").strip()
	message = (message or "").strip()
	if not subject:
		frappe.throw(_("Subject is required."))
	if not message:
		frappe.throw(_("Please enter a message."))
	if not (to_customer or to_transporter):
		frappe.throw(_("Choose at least one audience: customer or transporter."))
	if update_source not in CGM_SOURCES:
		frappe.throw(_("Published updates must come from a CGM source."))
	if not project and container_tracker:
		project = frappe.db.get_value("Container Tracker", container_tracker, "project")
	# A reply inherits its context; only a fresh post has to name a shipment.
	if not project and not parent_update:
		frappe.throw(_("Select the shipment this update belongs to."))

	if to_transporter and not transporter:
		transporter = _transporter_for_context(
			project=project, container_tracker=container_tracker, allocation=allocation
		)

	return create_update(
		update_source=update_source,
		subject=subject,
		message=message,
		project=project,
		container_tracker=container_tracker,
		transporter=transporter,
		allocation=allocation,
		attachment=attachment,
		event_date=event_date,
		visible_to_customer=bool(to_customer),
		visible_to_transporter=bool(to_transporter),
		parent_update=_validated_parent(parent_update, project=project),
		notify=True,
	)


def _transporter_for_context(
	*,
	project: str | None = None,
	container_tracker: str | None = None,
	allocation: str | None = None,
) -> str | None:
	"""Best-effort transporter for an update CGM is publishing to transport."""
	if allocation:
		return frappe.db.get_value("Container Allocation", allocation, "transporter")
	if container_tracker:
		transporter = frappe.db.get_value("Container Tracker", container_tracker, "transporter")
		if transporter:
			return transporter
	if project:
		return frappe.db.get_value(
			"Container Allocation",
			{"project": project, "docstatus": 1},
			"transporter",
			order_by="modified desc",
		)
	return None


def post_update_reply(
	parent_update: str,
	message: str,
	*,
	subject: str | None = None,
	to_customer: bool | None = None,
	to_transporter: bool | None = None,
	attachment: str = "",
) -> dict:
	"""CGM replies to a customer or transporter message, keeping the thread links."""
	parent = frappe.get_doc(UPDATE_DOCTYPE, parent_update, ignore_permissions=True)

	# Default the audience to whoever started the thread.
	if to_customer is None:
		to_customer = parent.update_source == "Customer" or bool(parent.visible_to_customer)
	if to_transporter is None:
		to_transporter = parent.update_source == "Transporter" or bool(
			parent.visible_to_transporter
		)

	reply_subject = (subject or "").strip() or _("Re: {0}").format(parent.subject)

	result = post_published_update(
		subject=reply_subject,
		message=message,
		project=parent.project,
		container_tracker=parent.container_tracker,
		to_customer=bool(to_customer),
		to_transporter=bool(to_transporter),
		transporter=parent.transporter,
		allocation=parent.allocation,
		parent_update=parent.name,
		attachment=attachment,
	)
	stamp_response_on_question(parent.name, result["name"])
	result["update"] = serialize_update(
		frappe.get_doc(UPDATE_DOCTYPE, result["name"], ignore_permissions=True)
	)
	return result


def stamp_response_on_question(question: str, reply: str) -> bool:
	"""Record who at CGM answered a party's question, and when.

	Only the first answer is recorded - the point is accountability for the
	question being picked up, so a later follow-up must not overwrite who
	actually responded.
	"""
	row = frappe.db.get_value(
		UPDATE_DOCTYPE,
		question,
		["name", "update_source", "response_status", "responded_by"],
		as_dict=True,
	)
	if not row or row.update_source not in PARTY_SOURCES:
		return False
	if row.response_status == "Answered" and row.responded_by:
		return False

	frappe.db.set_value(
		UPDATE_DOCTYPE,
		question,
		{
			"response_status": "Answered",
			"responded_by": frappe.session.user,
			"responded_on": now_datetime(),
			"response_update": reply,
		},
		update_modified=False,
	)
	frappe.clear_document_cache(UPDATE_DOCTYPE, question)
	return True


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
	"""Update cards for server-rendered pages - same markup as the Desk feed.

	The transporter portal renders its truck updates without JavaScript, so the
	structure here has to match `cgm.updates.renderListItem` or the two would
	drift apart visually.
	"""
	from frappe.utils import escape_html, pretty_date

	rows = rows or []
	if not rows:
		return ""

	cards: list[str] = []
	for row in rows:
		subject = escape_html(row.get("subject") or row.get("update_type") or _("Update"))
		source = (row.get("update_source") or "").strip() if show_source else ""
		source_tag = (
			f'<span class="cgm-upd-tag is-source is-{escape_html(source.lower())}">'
			f"{escape_html(source)}</span>"
			if source
			else ""
		)

		status = row.get("response_status") or ""
		if status == "Open":
			state_tag = f'<span class="cgm-upd-tag is-awaiting">{escape_html(_("Awaiting reply"))}</span>'
		elif status == "Answered":
			state_tag = f'<span class="cgm-upd-tag is-answered">{escape_html(_("Answered"))}</span>'
		else:
			state_tag = ""

		when = ""
		if row.get("posted_on"):
			try:
				when = escape_html(pretty_date(row["posted_on"]))
			except Exception:
				when = escape_html(str(row["posted_on"]))

		chips: list[str] = []
		shipment = row.get("project_ref") or row.get("project")
		if shipment:
			chips.append(f'<span class="cgm-upd-chip is-ref">{escape_html(shipment)}</span>')
		customer = row.get("customer_name") or row.get("customer")
		if customer:
			chips.append(f'<span class="cgm-upd-chip">{escape_html(customer)}</span>')
		if row.get("container_number"):
			chips.append(
				f'<span class="cgm-upd-chip is-ref">{escape_html(row["container_number"])}</span>'
			)
		meta_html = f'<div class="cgm-upd-meta">{"".join(chips)}</div>' if chips else ""

		preview = _preview_message(row.get("message") or "")
		preview_html = (
			f'<p class="cgm-upd-preview">{escape_html(preview)}</p>' if preview else ""
		)

		answered_html = ""
		if status == "Answered" and row.get("responded_by_name"):
			answered_html = (
				f'<div class="cgm-upd-answer">'
				f'{escape_html(_("Answered by {0}").format(row["responded_by_name"]))}</div>'
			)

		name = escape_html(row.get("name") or "")
		classes = "cgm-upd-card"
		if not cint(row.get("is_read")):
			classes += " is-unread"
		if status == STATUS_OPEN:
			classes += " is-awaiting"
		elif status == STATUS_ANSWERED:
			classes += " is-answered"
		elif status == STATUS_CLOSED:
			classes += " is-closed"

		cards.append(
			f'<div class="{classes}" data-update="{name}" role="button" tabindex="0">'
			f'<div class="cgm-upd-headline">'
			f'<span class="cgm-upd-title">{subject}</span>{source_tag}{state_tag}'
			f'<span class="cgm-upd-stamp">'
			f'<span class="cgm-upd-ref">{name}</span>'
			+ (f'<span class="cgm-upd-when">{when}</span>' if when else "")
			+ f"</span></div>"
			f"{meta_html}{preview_html}{answered_html}"
			f"</div>"
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
		FROM `tabShipment Update` t
		INNER JOIN (
			SELECT container_tracker, MAX(posted_on) AS max_posted
			FROM `tabShipment Update`
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
	label = " - ".join(p for p in parts if p)
	posted = update.get("posted_on")
	if posted:
		formatted = frappe.format(posted, {"fieldtype": "Datetime"})
		label = f"{label} ({formatted})"
	return label


@frappe.whitelist()
def get_allocation_truck_updates(allocation_name: str) -> list[dict]:
	"""Updates linked to this allocation, its containers, or its shipment."""
	require_desk_access()
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
	require_desk_access()
	frappe.has_permission("Container Tracker", ptype="read", doc=container_tracker, throw=True)
	return get_updates_for_container_tracker(container_tracker)


@frappe.whitelist()
def get_project_updates(project: str) -> list[dict]:
	require_desk_access()
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	return get_updates_for_project(project)


@frappe.whitelist()
def get_ops_updates(filters=None) -> dict:
	"""Paginated updates feed for the Container Ops Board Updates tab."""
	require_desk_access()
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

	# Replies belong to the question they answer, and the card's View More
	# shows the whole exchange - listing them separately doubles every thread.
	# `include_replies` opts back in.
	if not cint(filters.get("include_replies")):
		query_filters["parent_update"] = ("is", "not set")

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
	elif status in ("Awaiting Reply", "awaiting reply", "Open"):
		query_filters["response_status"] = STATUS_OPEN
		query_filters["update_source"] = ("in", list(PARTY_SOURCES))
	elif status in ("Answered", "answered"):
		query_filters["response_status"] = STATUS_ANSWERED
	elif status in ("Closed", "closed"):
		query_filters["response_status"] = STATUS_CLOSED
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
		# Newest activity first: a thread rises when a reply lands on it, not
		# only when the question was first raised. `last_activity_on` is set on
		# every insert and backfilled, so posted_on is only a tiebreak.
		order_by="last_activity_on desc, posted_on desc",
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
	require_desk_access()
	return frappe.db.count(
		UPDATE_DOCTYPE,
		{"is_read": 0, "update_source": ("in", ["Transporter", "Customer"])},
	)


@frappe.whitelist()
def get_awaiting_reply_count() -> int:
	"""Questions from customers and transporters that CGM has not answered."""
	require_desk_access()
	return frappe.db.count(
		UPDATE_DOCTYPE,
		{
			"response_status": "Open",
			"update_source": ("in", list(PARTY_SOURCES)),
			# One row per thread, so the badge matches the Awaiting Reply filter.
			"parent_update": ("is", "not set"),
		},
	)


@frappe.whitelist()
def mark_update_read(name: str) -> dict:
	if is_portal_user():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
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
	if not portal and fieldtype in ("Date", "Datetime"):
		# Desk keeps the real control (it shows the timezone hint), but the
		# control parses strictly: a datetime carrying microseconds fails
		# validation with "must be in format: dd-mm-yyyy".
		try:
			if fieldtype == "Datetime":
				display = get_datetime(value).strftime("%Y-%m-%d %H:%M:%S")
			else:
				display = getdate(value).strftime("%Y-%m-%d")
		except Exception:
			display = str(value)

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
	doc,
	*,
	include_source: bool = True,
	portal: bool = False,
	with_transcript: bool = False,
) -> list[dict]:
	"""Data-driven dialog sections — only fields with values, source-aware.

	`with_transcript` means the dialog is also rendering the conversation, which
	already carries every message and who answered - so the Message and
	Response blocks are dropped rather than repeated.
	"""
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

	# CGM's own updates are not questions, so they carry no response state.
	# The transcript states who answered, so this only appears without one.
	response_fields = [] if with_transcript else [
		f
		for f in (

			_detail_field(
				"response_status", _("Response Status"), "Data", doc.get("response_status"),
				portal=portal,
			),
			_detail_field(
				"responded_by",
				_("Responded By"),
				"Link",
				doc.get("responded_by"),
				options="User",
				portal=portal,
			),
			_column_break("column_break_response_detail"),
			_detail_field(
				"responded_on", _("Responded On"), "Datetime", doc.get("responded_on"),
				portal=portal,
			),
		)
		if f
	]
	# Only a party's message carries response state, and a lone column break
	# is not worth a section.
	if doc.update_source in PARTY_SOURCES and [
		f for f in response_fields if f["fieldtype"] != "Column Break"
	]:
		sections.append({"label": _("Response"), "fields": response_fields})

	message_fields = [] if with_transcript else [
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
	if not cint(doc.get("visible_to_transporter")):
		# Internal notes stay internal even on the transporter's own allocation.
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
	if not cint(doc.get("visible_to_customer")):
		# Internal notes stay internal even on the customer's own shipment.
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

	if not portal and is_portal_user():
		# A portal account that fails both ownership rules is done here; the
		# desk check below would otherwise pass for portal roles that carry a
		# DocPerm on Update and hand over an internal note.
		frappe.throw(_("Not permitted"), frappe.PermissionError)

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
	# Desk gets the whole conversation so ops can read what was asked and what
	# was answered without leaving the dialog. The portals render their own
	# threads and must not receive messages published to the other party.
	payload["thread"] = [] if portal else message_thread(doc.name)
	payload["sections"] = _build_update_detail_sections(
		doc,
		include_source=show_source,
		portal=portal or not show_source,
		with_transcript=bool(payload["thread"]),
	)
	return payload





# ─── Portal conversation threads ─────────────────────────────────────────────
#
# A "thread" is the two-way conversation one portal party can see on a
# shipment or on a single container: everything that party posted plus every
# CGM update published to them. Visibility is driven entirely by the
# `visible_to_customer` / `visible_to_transporter` flags, so an internal note
# can never reach a portal by accident.


def _thread_rows(filters: dict, limit: int = 100) -> list[dict]:
	return frappe.get_all(
		UPDATE_DOCTYPE,
		filters=filters,
		fields=_UPDATE_LIST_FIELDS,
		order_by="posted_on asc",
		limit_page_length=limit,
		ignore_permissions=True,
	)


def _thread_payload(rows: list[dict], *, audience: str) -> list[dict]:
	"""Serialize rows oldest-first and tag each message with its direction."""
	seen: set[str] = set()
	messages: list[dict] = []
	for row in rows:
		if row["name"] in seen:
			continue
		seen.add(row["name"])
		message = serialize_update(frappe._dict(row))
		message["direction"] = "in" if message["from_cgm"] else "out"
		read_field = "customer_read_on" if audience == AUDIENCE_CUSTOMER else "transporter_read_on"
		message["unread"] = bool(message["from_cgm"] and not row.get(read_field))
		messages.append(message)
	messages.sort(key=lambda m: m.get("posted_on") or "")
	return messages


def get_customer_thread_for_project(
	project: str, *, container_tracker: str | None = None, limit: int = 200
) -> list[dict]:
	"""Customer-visible conversation on a shipment (or one of its containers).

	Callers must have already verified that the shipment belongs to the
	logged-in customer.
	"""
	if not project or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return []
	filters: dict = {"project": project, "visible_to_customer": 1}
	if container_tracker:
		filters["container_tracker"] = container_tracker
	return _thread_payload(_thread_rows(filters, limit), audience=AUDIENCE_CUSTOMER)


def get_customer_general_thread(customer: str, limit: int = 200) -> list[dict]:
	"""The customer's conversation with operations that is not about a shipment."""
	if not customer or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return []
	rows = _thread_rows(
		{"customer": customer, "project": ("is", "not set"), "visible_to_customer": 1}, limit
	)
	return _thread_payload(rows, audience=AUDIENCE_CUSTOMER)


def get_transporter_thread_for_allocation(
	allocation_name: str,
	transporter: str,
	*,
	container_tracker: str | None = None,
	limit: int = 200,
) -> list[dict]:
	"""Transporter-visible conversation on an allocation (or one container).

	Built from three scopes that are each safe on their own - the allocation,
	its containers, and shipment-level updates addressed to this transporter -
	rather than one broad "same project" filter, which would show a shipment's
	other hauliers' messages.
	"""
	if not allocation_name or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return []

	allocation = frappe.db.get_value(
		"Container Allocation", allocation_name, ["name", "project", "transporter"], as_dict=True
	)
	if not allocation or allocation.transporter != transporter:
		return []

	trackers = [
		t
		for t in frappe.get_all(
			"Container Allocation Item",
			filters={"parent": allocation_name, "parenttype": "Container Allocation"},
			pluck="container_tracker",
			ignore_permissions=True,
		)
		if t
	]
	if container_tracker:
		if container_tracker not in trackers:
			return []
		trackers = [container_tracker]

	scopes: list[dict] = []
	if container_tracker:
		scopes.append({"visible_to_transporter": 1, "container_tracker": container_tracker})
	else:
		scopes.append({"visible_to_transporter": 1, "allocation": allocation_name})
		if trackers:
			scopes.append({"visible_to_transporter": 1, "container_tracker": ("in", trackers)})
		if allocation.project:
			scopes.append(
				{
					"visible_to_transporter": 1,
					"project": allocation.project,
					"transporter": transporter,
				}
			)

	rows: list[dict] = []
	for scope in scopes:
		rows.extend(_thread_rows(scope, limit))
	return _thread_payload(rows, audience=AUDIENCE_TRANSPORTER)


def mark_thread_read(names: list[str] | str, audience: str) -> int:
	"""Stamp the audience's read timestamp on CGM messages they just opened."""
	if isinstance(names, str):
		names = frappe.parse_json(names) if names.strip().startswith("[") else [names]
	names = [n for n in (names or []) if n]
	if not names:
		return 0

	field = "customer_read_on" if audience == AUDIENCE_CUSTOMER else "transporter_read_on"
	flag = "visible_to_customer" if audience == AUDIENCE_CUSTOMER else "visible_to_transporter"
	stamped = now_datetime()
	count = 0
	for name in names:
		row = frappe.db.get_value(
			UPDATE_DOCTYPE, name, ["name", field, flag, "update_source"], as_dict=True
		)
		if not row or row.get(field) or not cint(row.get(flag)):
			continue
		if row.update_source not in CGM_SOURCES:
			continue
		frappe.db.set_value(UPDATE_DOCTYPE, name, field, stamped, update_modified=False)
		count += 1
	return count


def count_unread_customer_updates(customer: str, project: str | None = None) -> int:
	"""CGM messages published to this customer that they have not opened yet."""
	if not customer or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return 0

	source_placeholders = ", ".join(["%s"] * len(CGM_SOURCES))
	conditions = [
		"u.visible_to_customer = 1",
		"u.customer_read_on IS NULL",
		"p.customer = %s",
		f"u.update_source IN ({source_placeholders})",
	]
	values: list = [customer, *CGM_SOURCES]
	if project:
		conditions.append("u.project = %s")
		values.append(project)

	rows = frappe.db.sql(
		f"""
		SELECT COUNT(*)
		FROM `tabShipment Update` u
		JOIN `tabProject` p ON p.name = u.project
		WHERE {" AND ".join(conditions)}
		""",
		tuple(values),
	)
	return (rows[0][0] if rows else 0) or 0


def count_unread_transporter_updates(transporter: str, allocation: str | None = None) -> int:
	"""CGM messages published to this transporter that they have not opened yet."""
	if not transporter or not frappe.db.exists("DocType", UPDATE_DOCTYPE):
		return 0
	filters: dict = {
		"visible_to_transporter": 1,
		"transporter_read_on": ("is", "not set"),
		"transporter": transporter,
		"update_source": ("in", list(CGM_SOURCES)),
	}
	if allocation:
		filters["allocation"] = allocation
	return frappe.db.count(UPDATE_DOCTYPE, filters)


# ─── Desk endpoints: publishing and replying to portal parties ───────────────


@frappe.whitelist()
def publish_update(
	subject: str,
	message: str,
	project: str | None = None,
	container_tracker: str | None = None,
	to_customer: int | str = 0,
	to_transporter: int | str = 0,
	update_source: str = "Internal",
	allocation: str | None = None,
	attachment: str = "",
	event_date: str | None = None,
) -> dict:
	"""Desk: post an update that the customer and/or transporter can read."""
	require_desk_access(ptype="create")
	return post_published_update(
		subject=subject,
		message=message,
		project=project,
		container_tracker=container_tracker,
		to_customer=bool(cint(to_customer)),
		to_transporter=bool(cint(to_transporter)),
		update_source=update_source,
		allocation=allocation,
		attachment=attachment,
		event_date=event_date,
	)


@frappe.whitelist()
def reply_to_update(
	name: str,
	message: str,
	subject: str | None = None,
	to_customer: int | str | None = None,
	to_transporter: int | str | None = None,
	attachment: str = "",
) -> dict:
	"""Desk: reply to a customer or transporter message inside its thread."""
	require_desk_access(ptype="create")
	if not frappe.db.exists(UPDATE_DOCTYPE, name):
		frappe.throw(_("Update not found."), frappe.DoesNotExistError)

	result = post_update_reply(
		name,
		message,
		subject=subject,
		to_customer=None if to_customer is None else bool(cint(to_customer)),
		to_transporter=None if to_transporter is None else bool(cint(to_transporter)),
		attachment=attachment,
	)
	# The message being answered has now been dealt with.
	frappe.db.set_value(UPDATE_DOCTYPE, name, "is_read", 1, update_modified=False)
	result["message"] = _("Reply sent.")
	return result


def thread_root(name: str) -> str | None:
	"""The message a thread hangs off - replies attach to it, as does status."""
	row = frappe.db.get_value(UPDATE_DOCTYPE, name, ["name", "parent_update"], as_dict=True)
	if not row:
		return None
	return row.parent_update or row.name


def set_thread_status(name: str, status: str) -> dict:
	"""Close or reopen a conversation.

	Status lives on the thread's root, which is the row the ops feed lists and
	the row every reply hangs off.
	"""
	if status not in (STATUS_OPEN, STATUS_CLOSED):
		frappe.throw(_("Unknown conversation status."))

	root = thread_root(name)
	if not root:
		frappe.throw(_("Conversation not found."), frappe.DoesNotExistError)

	row = frappe.db.get_value(
		UPDATE_DOCTYPE, root, ["update_source", "responded_by"], as_dict=True
	)
	if not row or row.update_source not in PARTY_SOURCES:
		frappe.throw(_("Only a customer or transporter question can be closed."))

	if status == STATUS_CLOSED:
		values = {
			"response_status": STATUS_CLOSED,
			"closed_by": frappe.session.user,
			"closed_on": now_datetime(),
		}
		message = _("Conversation closed.")
	else:
		# Reopening returns it to whichever side of the exchange it was on:
		# answered before means CGM owes nothing until the party writes again.
		values = {
			"response_status": STATUS_ANSWERED if row.responded_by else STATUS_OPEN,
			"closed_by": None,
			"closed_on": None,
		}
		message = _("Conversation reopened.")

	frappe.db.set_value(UPDATE_DOCTYPE, root, values, update_modified=False)
	frappe.clear_document_cache(UPDATE_DOCTYPE, root)
	return {"ok": True, "name": root, "status": values["response_status"], "message": message}


def message_thread(name: str) -> list[dict]:
	"""The whole conversation a message belongs to, oldest first.

	A thread is one root message plus every reply pointing at it, so opening
	any message in it returns the same transcript.
	"""
	root = frappe.db.get_value(UPDATE_DOCTYPE, name, ["name", "parent_update"], as_dict=True)
	if not root:
		return []
	root_name = root.parent_update or root.name

	rows = _thread_rows({"name": root_name})
	rows.extend(_thread_rows({"parent_update": root_name}))
	seen: set[str] = set()
	messages: list[dict] = []
	for row in rows:
		if row["name"] in seen:
			continue
		seen.add(row["name"])
		messages.append(serialize_update(frappe._dict(row)))
	messages.sort(key=lambda m: m.get("posted_on") or "")
	return messages


@frappe.whitelist()
def get_update_thread(name: str) -> list[dict]:
	"""Desk: the whole conversation a message belongs to, oldest first."""
	require_desk_access(doc=name)
	return message_thread(name)
