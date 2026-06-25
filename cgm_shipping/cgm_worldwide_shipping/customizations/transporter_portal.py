# Copyright (c) 2026, Titansoft Limited and contributors
"""Transporter portal data layer and whitelisted APIs."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import frappe
from frappe import _

from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
	ALLOCATION_STATUS_ACKNOWLEDGED,
	ALLOCATION_STATUS_ALLOCATED,
	ASSIGNMENT_INTERCHANGE,
	ASSIGNMENT_PENDING,
	ASSIGNMENT_TRUCK,
	acknowledge_allocation,
	save_assignment_draft,
	submit_truck_assignment,
	sync_interchange_from_item,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
	compute_container_metrics,
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


def list_my_allocations(transporter: str) -> list[dict]:
	"""Allocations for a transporter — scoped server-side, ignores desk permissions."""
	if not transporter:
		return []

	rows = frappe.get_all(
		"Container Allocation",
		filters={
			"transporter": transporter,
			"docstatus": 1,
			"status": ("in", (ALLOCATION_STATUS_ALLOCATED, ALLOCATION_STATUS_ACKNOWLEDGED)),
		},
		fields=[
			"name",
			"project",
			"bill_of_lading",
			"allocation_date",
			"status",
		],
		order_by="allocation_date desc, modified desc",
		ignore_permissions=True,
	)

	out: list[dict] = []
	for row in rows:
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

		out.append(
			{
				"name": row.name,
				"project": row.project,
				"project_ref": _project_display_ref(row.project),
				"bill_of_lading": row.bill_of_lading or "",
				"allocation_date": row.allocation_date,
				"status": row.status,
				"container_total": counts["total"],
				"pending_count": counts.get(ASSIGNMENT_PENDING, 0),
				"truck_assigned_count": counts.get(ASSIGNMENT_TRUCK, 0),
				"interchange_count": counts.get(ASSIGNMENT_INTERCHANGE, 0),
			}
		)
	return out


@frappe.whitelist()
def get_my_allocations() -> list[dict]:
	transporter = require_transporter_portal_access()
	return list_my_allocations(transporter)


@frappe.whitelist()
def get_allocation_detail(allocation_name: str) -> dict:
	transporter = require_transporter_portal_access()
	allocation = _get_allocation_for_transporter(allocation_name, transporter)
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
		if tracker_data.get("interchange_document"):
			interchange_url = tracker_data["interchange_document"]

		truck_number = (row.truck_number or "").strip()
		driver_name = (row.driver_name or "").strip()
		driver_contact = (row.driver_contact or "").strip()
		assignment_status = row.assignment_status or ASSIGNMENT_PENDING

		containers.append(
			{
				"name": row.name,
				"container_tracker": row.container_tracker,
				"container_number": row.container_number or tracker_data.get("container_number"),
				"type_of_container": row.type_of_container or tracker_data.get("type_of_container"),
				"truck_number": truck_number,
				"driver_name": driver_name,
				"driver_contact": driver_contact,
				"assignment_status": assignment_status,
				"has_draft": assignment_status == ASSIGNMENT_PENDING
				and bool(truck_number or driver_name or driver_contact),
				"tracker_status": tracker_data.get("status") or "",
				"tracker_alert": tracker_data.get("alert_status") or "",
				"interchange_document": interchange_url,
				"interchange_date": tracker_data.get("interchange_date"),
			}
		)

	return {
		"name": allocation.name,
		"project": allocation.project,
		"project_ref": project_ref,
		"bill_of_lading": allocation.bill_of_lading or "",
		"allocation_date": allocation.allocation_date,
		"status": allocation.status,
		"containers": containers,
	}


@frappe.whitelist()
def save_truck_assignment(
	allocation_name: str,
	item_name: str,
	truck_number: str,
	driver_name: str,
	driver_contact: str = "",
) -> dict:
	"""Save truck/driver draft on the allocation row (status stays Pending)."""
	transporter = require_transporter_portal_access()
	_get_allocation_for_transporter(allocation_name, transporter)
	return save_assignment_draft(
		allocation_name,
		item_name,
		truck_number,
		driver_name,
		driver_contact,
	)


@frappe.whitelist()
def submit_truck_assignment_portal(
	allocation_name: str,
	item_name: str,
	truck_number: str,
	driver_name: str,
	driver_contact: str = "",
) -> dict:
	"""Confirm truck assignment and sync to Container Tracker."""
	transporter = require_transporter_portal_access()
	_get_allocation_for_transporter(allocation_name, transporter)
	return submit_truck_assignment(
		allocation_name,
		item_name,
		truck_number,
		driver_name,
		driver_contact,
	)


@frappe.whitelist()
def upload_interchange(
	allocation_name: str,
	item_name: str,
	interchange_document: str,
	interchange_date: str | None = None,
) -> dict:
	transporter = require_transporter_portal_access()
	_assert_allocation_for_transporter(allocation_name, transporter)
	return sync_interchange_from_item(
		allocation_name,
		item_name,
		interchange_document,
		interchange_date,
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
