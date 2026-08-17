# Copyright (c) 2026, Titansoft Limited and contributors
"""Transporter portal data layer and whitelisted APIs."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint

from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
	ALLOCATION_STATUS_ACKNOWLEDGED,
	ALLOCATION_STATUS_ALLOCATED,
	ALLOCATION_STATUS_COMPLETED,
	ASSIGNMENT_INTERCHANGE,
	ASSIGNMENT_PENDING,
	ASSIGNMENT_TRUCK,
	OFFERED_TRUCK_OFFERED,
	OFFERED_TRUCK_WITHDRAWN,
	acknowledge_allocation,
	submit_offered_trucks,
	sync_interchange_from_item,
	withdraw_offered_truck,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	compute_container_metrics,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates import (
	TRANSPORTER_SUBJECTS,
	get_my_updates_for_allocation,
	get_updates_for_allocation_item,
	post_truck_update,
	render_updates_list_html,
)


def get_transporter_for_user(user: str | None = None) -> str | None:
	"""Resolve the transporter Supplier linked to a portal user."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return None

	rows = frappe.get_all(
		"Portal User",
		filters={"user": user, "parenttype": "Supplier"},
		fields=["parent"],
		limit=50,
	)
	for row in rows:
		if frappe.db.get_value("Supplier", row.parent, "is_transporter"):
			return row.parent

	contact = frappe.db.get_value("Contact", {"user": user}, "name") or frappe.db.get_value(
		"Contact", {"email_id": user}, "name"
	)
	if not contact:
		return None

	linked_suppliers = frappe.get_all(
		"Dynamic Link",
		filters={
			"parent": contact,
			"parenttype": "Contact",
			"link_doctype": "Supplier",
		},
		pluck="link_name",
	)
	for supplier in linked_suppliers:
		if frappe.db.get_value("Supplier", supplier, "is_transporter"):
			portal_user = frappe.db.exists(
				"Portal User", {"parent": supplier, "parenttype": "Supplier", "user": user}
			)
			if portal_user:
				return supplier
	return None


def transporter_display_name(transporter: str | None) -> str:
	if not transporter:
		return ""
	return frappe.db.get_value("Supplier", transporter, "supplier_name") or transporter


def require_transporter_portal_access() -> str:
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote("/transporter", safe="")
		raise frappe.Redirect

	transporter = get_transporter_for_user()
	if not transporter:
		frappe.throw(
			_("Your account is not linked to a transporter company. Contact CGM operations."),
			frappe.PermissionError,
		)

	return transporter


def _assert_allocation_for_transporter(allocation_name: str, transporter: str):
	return _get_allocation_for_transporter(allocation_name, transporter)


def _get_allocation_for_transporter(allocation_name: str, transporter: str):
	if not frappe.db.exists("Container Allocation", allocation_name):
		frappe.throw(_("Allocation not found."), frappe.DoesNotExistError)

	allocation = frappe.get_doc("Container Allocation", allocation_name, ignore_permissions=True)
	if allocation.transporter != transporter:
		frappe.throw(_("You do not have access to this allocation."), frappe.PermissionError)
	if allocation.docstatus != 1:
		frappe.throw(_("This allocation is not active."), frappe.PermissionError)
	return allocation


def _project_display_ref(project_name: str | None) -> str:
	if not project_name or not frappe.db.exists("Project", project_name):
		return project_name or ""
	from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
		get_project_reference,
	)

	doc = frappe.get_doc("Project", project_name, ignore_permissions=True)
	return get_project_reference(doc) or doc.get("project_name") or project_name


def _summarize_allocation_row(row: dict) -> dict:
	items = frappe.get_all(
		"Container Allocation Item",
		filters={"parent": row.name},
		fields=["assignment_status"],
		ignore_permissions=True,
	)
	counts = {
		"total": len(items),
		ASSIGNMENT_PENDING: 0,
		ASSIGNMENT_TRUCK: 0,
		ASSIGNMENT_INTERCHANGE: 0,
	}
	for item in items:
		status = item.assignment_status or ASSIGNMENT_PENDING
		counts[status] = counts.get(status, 0) + 1

	is_completed = row.status == ALLOCATION_STATUS_COMPLETED
	return {
		"name": row.name,
		"project": row.project,
		"project_ref": _project_display_ref(row.project),
		"bill_of_lading": row.bill_of_lading or "",
		"allocation_date": row.allocation_date,
		"status": row.status,
		"is_completed": is_completed,
		"container_total": counts["total"],
		"trucks_booked": cint(row.get("trucks_booked")) or counts["total"],
		"pending_count": counts.get(ASSIGNMENT_PENDING, 0),
		"truck_assigned_count": counts.get(ASSIGNMENT_TRUCK, 0),
		"interchange_count": counts.get(ASSIGNMENT_INTERCHANGE, 0),
	}


def _list_allocations_for_statuses(transporter: str, statuses: tuple[str, ...]) -> list[dict]:
	if not transporter or not statuses:
		return []

	rows = frappe.get_all(
		"Container Allocation",
		filters={
			"transporter": transporter,
			"docstatus": 1,
			"status": ("in", statuses),
		},
		fields=[
			"name",
			"project",
			"bill_of_lading",
			"allocation_date",
			"status",
			"trucks_booked",
		],
		order_by="allocation_date desc, modified desc",
		ignore_permissions=True,
	)
	return [_summarize_allocation_row(row) for row in rows]


def list_my_allocations(transporter: str) -> dict[str, list[dict]]:
	"""Active and completed allocations for the transporter portal home page."""
	return {
		"active": _list_allocations_for_statuses(
			transporter, (ALLOCATION_STATUS_ALLOCATED, ALLOCATION_STATUS_ACKNOWLEDGED)
		),
		"completed": _list_allocations_for_statuses(transporter, (ALLOCATION_STATUS_COMPLETED,)),
	}


def list_my_allocations_flat(transporter: str) -> list[dict]:
	"""All portal allocations (active first, then completed)."""
	grouped = list_my_allocations(transporter)
	return grouped["active"] + grouped["completed"]


def get_transporter_portal_dashboard(transporter: str) -> dict:
	"""Summary stats + allocation lists for the transporter portal home page."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share import (
		get_transporter_invoice_summary,
	)

	grouped = list_my_allocations(transporter)
	active = grouped["active"]
	completed = grouped["completed"]

	pending = sum(int(r.get("pending_count") or 0) for r in active)
	assigned = sum(int(r.get("truck_assigned_count") or 0) for r in active)
	interchange_on_active = sum(int(r.get("interchange_count") or 0) for r in active)
	completed_containers = sum(int(r.get("container_total") or 0) for r in completed)

	for row in active:
		total = int(row.get("container_total") or 0)
		done = int(row.get("interchange_count") or 0)
		row["progress_label"] = f"{done}/{total}" if total else "0/0"

	for row in completed:
		total = int(row.get("container_total") or 0)
		row["progress_label"] = f"{total}/{total}" if total else "0/0"

	invoice_summary = get_transporter_invoice_summary(transporter)
	return {
		"active_allocations": active,
		"completed_allocations": completed,
		"stat_active_allocations": len(active),
		"stat_completed_allocations": len(completed),
		"stat_pending_containers": pending,
		"stat_assigned_containers": assigned,
		"stat_complete_containers": interchange_on_active + completed_containers,
		"stat_total_containers": sum(int(r.get("container_total") or 0) for r in active)
		+ completed_containers,
		"stat_invoice_count": invoice_summary["stat_invoice_count"],
		"stat_outstanding_count": invoice_summary["stat_outstanding_count"],
		"stat_outstanding_amount": invoice_summary["stat_outstanding_amount"],
		"stat_paid_count": invoice_summary["stat_paid_count"],
		"invoice_currency": invoice_summary["currency"],
	}


@frappe.whitelist()
def get_my_allocations() -> list[dict]:
	transporter = require_transporter_portal_access()
	return list_my_allocations_flat(transporter)


@frappe.whitelist()
def get_allocation_detail(allocation_name: str) -> dict:
	transporter = require_transporter_portal_access()
	allocation = _get_allocation_for_transporter(allocation_name, transporter)
	if allocation.status != ALLOCATION_STATUS_COMPLETED:
		acknowledge_allocation(allocation_name)

	project_ref = _project_display_ref(allocation.project)

	containers: list[dict] = []
	for row in allocation.containers or []:
		tracker_data: dict[str, Any] = {}
		if row.container_tracker and frappe.db.exists("Container Tracker", row.container_tracker):
			tracker = frappe.get_doc(
				"Container Tracker", row.container_tracker, ignore_permissions=True
			).as_dict()
			tracker_data = compute_container_metrics(tracker)

		interchange_url = ""
		interchange_date_val = None
		row_interchange = (getattr(row, "interchange_document", None) or "").strip()
		if row_interchange:
			interchange_url = row_interchange
			interchange_date_val = row.interchange_date
		elif tracker_data.get("interchange_document"):
			interchange_url = tracker_data["interchange_document"]
			interchange_date_val = tracker_data.get("interchange_date")

		truck_number = (row.truck_number or "").strip()
		driver_name = (row.driver_name or "").strip()
		driver_contact = (row.driver_contact or "").strip()
		if not truck_number and tracker_data.get("truck_number"):
			truck_number = (tracker_data.get("truck_number") or "").strip()
		if not driver_name and tracker_data.get("driver_name"):
			driver_name = (tracker_data.get("driver_name") or "").strip()
		if not driver_contact and tracker_data.get("driver_contact"):
			driver_contact = (tracker_data.get("driver_contact") or "").strip()
		assignment_status = row.assignment_status or ASSIGNMENT_PENDING

		truck_updates = get_updates_for_allocation_item(
			row.name,
			container_tracker=row.container_tracker,
		)
		containers.append(
			{
				"name": row.name,
				"container_tracker": row.container_tracker,
				"container_number": row.container_number or tracker_data.get("container_number"),
				"cargo_size": row.cargo_size
				or getattr(row, "cargo_type", None)
				or tracker_data.get("cargo_size")
				or tracker_data.get("cargo_type"),
				"offered_truck": getattr(row, "offered_truck", None) or "",
				"truck_number": truck_number,
				"driver_name": driver_name,
				"driver_contact": driver_contact,
				"assignment_status": assignment_status,
				"has_interchange_draft": assignment_status == ASSIGNMENT_TRUCK and bool(row_interchange),
				"tracker_status": tracker_data.get("status") or "",
				"tracker_alert": tracker_data.get("alert_status") or "",
				"interchange_document": interchange_url,
				"interchange_date": interchange_date_val,
				"truck_updates": truck_updates,
			}
		)

	my_updates = get_my_updates_for_allocation(allocation.name, limit=100)
	container_options = [
		{
			"value": c["name"],
			"label": c.get("container_number") or c["name"],
			"container_number": c.get("container_number") or c["name"],
		}
		for c in containers
		if c.get("assignment_status") in (ASSIGNMENT_TRUCK, ASSIGNMENT_INTERCHANGE)
	]

	offered_trucks = []
	for truck in allocation.get("offered_trucks") or []:
		if truck.status == OFFERED_TRUCK_WITHDRAWN:
			continue
		offered_trucks.append(
			{
				"name": truck.name,
				"truck_number": truck.truck_number,
				"driver_name": truck.driver_name,
				"driver_contact": truck.driver_contact or "",
				"status": truck.status or OFFERED_TRUCK_OFFERED,
				"offered_on": truck.offered_on,
			}
		)

	pending_containers = sum(
		1 for c in containers if c.get("assignment_status") == ASSIGNMENT_PENDING
	)
	assigned_containers = sum(
		1 for c in containers if c.get("assignment_status") == ASSIGNMENT_TRUCK
	)

	return {
		"name": allocation.name,
		"project": allocation.project,
		"project_ref": project_ref,
		"bill_of_lading": allocation.bill_of_lading or "",
		"allocation_date": allocation.allocation_date,
		"status": allocation.status,
		"is_completed": allocation.status == ALLOCATION_STATUS_COMPLETED,
		"trucks_booked": cint(allocation.get("trucks_booked")) or len(containers),
		"container_total": len(containers),
		"pending_containers": pending_containers,
		"assigned_containers": assigned_containers,
		"offered_truck_count": len(offered_trucks),
		"containers": containers,
		"offered_trucks": offered_trucks,
		"my_updates": my_updates,
		"my_updates_html": render_updates_list_html(my_updates, show_source=False),
		"my_updates_json": frappe.as_json(my_updates),
		"container_options": container_options,
		"container_options_json": frappe.as_json(container_options),
		"update_types": list(TRANSPORTER_SUBJECTS),
		"update_types_json": frappe.as_json(list(TRANSPORTER_SUBJECTS)),
	}


@frappe.whitelist()
def submit_offered_trucks_portal(allocation_name: str, trucks) -> dict:
	"""Transporter batch-offers trucks + drivers for CGM to assign."""
	transporter = require_transporter_portal_access()
	_get_allocation_for_transporter(allocation_name, transporter)
	return submit_offered_trucks(allocation_name, trucks)


@frappe.whitelist()
def withdraw_offered_truck_portal(allocation_name: str, offered_truck_name: str) -> dict:
	"""Transporter withdraws an unassigned offered truck."""
	transporter = require_transporter_portal_access()
	_get_allocation_for_transporter(allocation_name, transporter)
	return withdraw_offered_truck(allocation_name, offered_truck_name)


@frappe.whitelist()
def save_truck_assignment(
	allocation_name: str,
	item_name: str,
	truck_number: str,
	driver_name: str,
	driver_contact: str = "",
) -> dict:
	"""Deprecated: transporters offer trucks in batch; CGM assigns containers."""
	transporter = require_transporter_portal_access()
	_get_allocation_for_transporter(allocation_name, transporter)
	frappe.throw(
		_(
			"Offer trucks in the Offered Trucks section. CGM assigns each container to a truck."
		),
		title=_("Use Offered Trucks"),
	)


@frappe.whitelist()
def submit_truck_assignment_portal(
	allocation_name: str,
	item_name: str,
	truck_number: str,
	driver_name: str,
	driver_contact: str = "",
) -> dict:
	"""Deprecated: transporters offer trucks in batch; CGM assigns containers."""
	transporter = require_transporter_portal_access()
	_get_allocation_for_transporter(allocation_name, transporter)
	frappe.throw(
		_(
			"Offer trucks in the Offered Trucks section. CGM assigns each container to a truck."
		),
		title=_("Use Offered Trucks"),
	)


@frappe.whitelist()
def save_interchange_draft_portal(
	allocation_name: str,
	item_name: str,
	interchange_document: str,
	interchange_date: str | None = None,
) -> dict:
	"""Save interchange draft on the allocation row (not sent to CGM until submit)."""
	transporter = require_transporter_portal_access()
	_assert_allocation_for_transporter(allocation_name, transporter)
	from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
		save_interchange_draft,
	)

	return save_interchange_draft(
		allocation_name,
		item_name,
		interchange_document,
		interchange_date,
	)


@frappe.whitelist()
def submit_interchange_portal(
	allocation_name: str,
	item_name: str,
) -> dict:
	"""Submit saved interchange to CGM (Container Tracker)."""
	transporter = require_transporter_portal_access()
	_assert_allocation_for_transporter(allocation_name, transporter)
	from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
		submit_interchange_from_item,
	)

	return submit_interchange_from_item(allocation_name, item_name)


@frappe.whitelist()
def upload_interchange(
	allocation_name: str,
	item_name: str,
	interchange_document: str,
	interchange_date: str | None = None,
) -> dict:
	"""Backward-compatible alias — saves interchange as draft."""
	transporter = require_transporter_portal_access()
	_assert_allocation_for_transporter(allocation_name, transporter)
	from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
		save_interchange_draft,
	)

	return save_interchange_draft(
		allocation_name,
		item_name,
		interchange_document,
		interchange_date,
	)


@frappe.whitelist()
def post_truck_update_portal(
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
) -> dict:
	"""Post a structured truck status update for one container."""
	transporter = require_transporter_portal_access()
	_get_allocation_for_transporter(allocation_name, transporter)
	return post_truck_update(
		allocation_name,
		item_name,
		update_type or subject,
		message=message,
		event_date=event_date,
		attachment=attachment,
		truck_number=truck_number,
		driver_name=driver_name,
		driver_contact=driver_contact,
		subject=subject or update_type,
		transporter=transporter,
	)


@frappe.whitelist()
def get_transporter_profile() -> dict:
	transporter = require_transporter_portal_access()
	supplier = frappe.get_doc("Supplier", transporter, ignore_permissions=True)
	return {
		"name": supplier.name,
		"supplier_name": supplier.supplier_name or supplier.name,
		"country": supplier.country or "",
		"supplier_group": supplier.supplier_group or "",
		"email_id": supplier.email_id or "",
		"mobile_no": supplier.mobile_no or "",
		"phone": supplier.get("phone") or "",
	}


def portal_context_base(context) -> str | None:
	"""Shared gate for transporter www pages. Returns transporter name or redirects."""
	context.no_cache = 1
	context.show_sidebar = False
	context.full_width = True

	if frappe.session.user == "Guest":
		path = frappe.local.request.path if frappe.local.request else "/transporter"
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(path, safe="")
		raise frappe.Redirect

	try:
		transporter = require_transporter_portal_access()
	except frappe.Redirect:
		raise
	except frappe.PermissionError as exc:
		context.is_transporter = False
		context.error_title = _("Access denied")
		context.error_message = exc.message or str(exc) or _(
			"You do not have access to the transporter portal."
		)
		return None
	except Exception:
		context.is_transporter = False
		context.error_title = _("Access denied")
		context.error_message = _("You do not have access to the transporter portal.")
		return None

	context.is_transporter = True
	context.transporter = transporter
	context.transporter_name = transporter_display_name(transporter)
	context.first_name = (
		frappe.db.get_value("User", frappe.session.user, "first_name") or frappe.session.user
	)
	return transporter
