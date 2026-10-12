"""Project custom fields and form layout (consolidated).

Idempotent installers called from migrate patches; primary field definitions live in
custom/project.json. Merged from the former project_shipment_fields /
project_container_tracking / project_tracking_layout modules.
"""
from __future__ import annotations

import json

import frappe
from frappe.utils import flt

from cgm_shipping.cgm_worldwide_shipping.customizations.permissions import (
	filter_sea_tasks_for_user,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
	get_project_reference,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
	derive_workflow_passed_states,
	derive_workflow_progress_from_tasks,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
	GENERIC_WORKFLOW_STATES,
	derive_generic_workflow_progress,
	get_workflow_tasks_for_project,
	project_uses_clearance_workflow_states,
	workflow_task_count_for_project,
)


MODULE = "CGM Worldwide Shipping"

SUPPLIER_CONTAINER_CHARGE_FIELDS = (
	"custom_section_shipping_line_rules",
	"custom_shipping_line_free_days_rules",
	"custom_shipping_line_demurrage_tiers",
)

SUPPLIER_LEGACY_CHARGE_FIELDS = (
	"custom_demurrage_free_days",
	"custom_demurrage_daily_rate",
	"custom_detention_free_days",
	"custom_detention_daily_rate",
	"custom_shipping_line_detention_tiers",
)


def _create_cf(dt: str, values: dict) -> None:
	name = f"{dt}-{values['fieldname']}"
	if frappe.db.exists("Custom Field", name):
		return
	doc = frappe.new_doc("Custom Field")
	doc.dt = dt
	doc.module = MODULE
	for key, value in values.items():
		setattr(doc, key, value)
	doc.insert(ignore_permissions=True)


def _remove_cf(dt: str, fieldname: str) -> None:
	name = f"{dt}-{fieldname}"
	if frappe.db.exists("Custom Field", name):
		frappe.delete_doc("Custom Field", name, force=1, ignore_permissions=True)


NON_LAYOUT_CF_KEYS = frozenset(
	{
		"fieldname",
		"insert_after",
		"label",
		"fieldtype",
		"options",
		"collapsible",
		"bold",
		"columns",
		"width",
	}
)


def _ensure_cf(dt: str, values: dict) -> None:
	"""Create a custom field if missing; never overwrite layout on existing fields.

	Desk exports (custom/*.json) and Customize Form are the source of truth for
	field order, labels, and insert_after. Migrate only creates missing fields and
	applies non-layout behaviour (read_only, cannot_add_rows, etc.).
	"""
	name = f"{dt}-{values['fieldname']}"
	if not frappe.db.exists("Custom Field", name):
		_create_cf(dt, values)
		return

	doc = frappe.get_doc("Custom Field", name)
	changed = False
	for key, value in values.items():
		if key in NON_LAYOUT_CF_KEYS:
			continue
		if doc.get(key) != value:
			doc.set(key, value)
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _upsert_cf(dt: str, values: dict) -> None:
	"""Create or update a Custom Field (keeps Supplier child tables in sync on migrate)."""
	name = f"{dt}-{values['fieldname']}"
	if frappe.db.exists("Custom Field", name):
		doc = frappe.get_doc("Custom Field", name)
		for key, value in values.items():
			setattr(doc, key, value)
		doc.save(ignore_permissions=True)
		return
	_create_cf(dt, values)


def _set_cf_property(fieldname: str, **kwargs) -> None:
	name = f"Project-{fieldname}"
	if not frappe.db.exists("Custom Field", name):
		return
	for key, value in kwargs.items():
		frappe.db.set_value("Custom Field", name, key, value, update_modified=False)


def check_project_layout_export_drift() -> list[str]:
	"""Return Project custom fields that exist in DB but are missing from field_order.

	When non-empty, export Customize Form to ``custom/project.json`` so production
	migrate applies the same layout (``sync_on_migrate``).
	"""
	ps_name = "Project-main-field_order"
	if not frappe.db.exists("Property Setter", ps_name):
		return []

	raw = frappe.db.get_value("Property Setter", ps_name, "value") or "[]"
	try:
		order = json.loads(raw)
	except json.JSONDecodeError:
		return []

	if not isinstance(order, list):
		return []

	order_set = set(order)
	return sorted(
		fn
		for fn in frappe.get_all("Custom Field", filters={"dt": "Project"}, pluck="fieldname")
		if fn not in order_set
	)


def ensure_supplier_field_order() -> None:
	"""Ensure CGM Supplier fields are listed in field_order (otherwise they stay hidden)."""
	ps_name = "Supplier-main-field_order"
	if not frappe.db.exists("Property Setter", ps_name):
		return
	raw = frappe.db.get_value("Property Setter", ps_name, "value") or "[]"
	try:
		order = json.loads(raw)
	except json.JSONDecodeError:
		return
	if not isinstance(order, list):
		return

	order = [
		f
		for f in order
		if f not in SUPPLIER_CONTAINER_CHARGE_FIELDS
		and f not in SUPPLIER_LEGACY_CHARGE_FIELDS
		and f != "custom_is_shipping_line"
	]

	# Place Is Shipping Line next to Is Transporter.
	if "is_transporter" in order:
		idx = order.index("is_transporter") + 1
		order.insert(idx, "custom_is_shipping_line")
	elif "custom_is_shipping_line" not in order:
		order.append("custom_is_shipping_line")

	anchor = "custom_is_shipping_line" if "custom_is_shipping_line" in order else (
		"image" if "image" in order else "supplier_group"
	)
	if anchor in order:
		idx = order.index(anchor) + 1
		for offset, fieldname in enumerate(SUPPLIER_CONTAINER_CHARGE_FIELDS):
			order.insert(idx + offset, fieldname)
	else:
		order.extend(SUPPLIER_CONTAINER_CHARGE_FIELDS)

	frappe.db.set_value(
		"Property Setter", ps_name, "value", json.dumps(order), update_modified=False
	)


def ensure_supplier_container_charge_fields() -> None:
	"""Shipping-line flag + child tables. Legacy fields removed — see custom/supplier.json."""
	for fieldname in SUPPLIER_LEGACY_CHARGE_FIELDS:
		_remove_cf("Supplier", fieldname)
	_upsert_cf(
		"Supplier",
		{
			"fieldname": "custom_is_shipping_line",
			"label": "Is Shipping Line",
			"fieldtype": "Check",
			"insert_after": "is_transporter",
			"description": "When checked, this supplier appears in Shipping Line link fields.",
		},
	)
	_upsert_cf(
		"Supplier",
		{
			"fieldname": "custom_section_shipping_line_rules",
			"label": "Container charge rules",
			"fieldtype": "Section Break",
			"insert_after": "custom_is_shipping_line",
			"collapsible": 1,
			"depends_on": "eval:doc.custom_is_shipping_line",
		},
	)
	insert_after = "custom_section_shipping_line_rules"
	for fieldname, label, options in (
		(
			"custom_shipping_line_free_days_rules",
			"Shipping Line Free Days Rules (optional reference)",
			"Shipping Line Free Days Rule",
		),
		(
			"custom_shipping_line_demurrage_tiers",
			"Shipping Line Demurrage Tiers",
			"Shipping Line Demurrage Tier",
		),
	):
		cf_values = {
			"fieldname": fieldname,
			"label": label,
			"fieldtype": "Table",
			"options": options,
			"insert_after": insert_after,
			"depends_on": "eval:doc.custom_is_shipping_line",
		}
		if fieldname == "custom_shipping_line_free_days_rules":
			cf_values["description"] = (
				"Optional reference only. Container Tracker free-day start/end dates "
				"drive demurrage day counts."
			)
		_upsert_cf("Supplier", cf_values)
		insert_after = fieldname
	ensure_supplier_field_order()
	frappe.clear_cache(doctype="Supplier")


def ensure_container_tracking_settings_fields() -> None:
	"""Container tracking settings live on CGM Shipping Settings doctype JSON.

	Remove legacy Custom Field duplicates from older installs.
	"""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CONTAINER_TASK_SEQ_DEFAULTS,
	)

	for fieldname in (
		"section_container_task_sequences",
		*CONTAINER_TASK_SEQ_DEFAULTS.keys(),
		"custom_kpa_free_days",
	):
		_remove_cf("CGM Shipping Settings", fieldname)

	if frappe.db.exists("DocType", "CGM Shipping Settings"):
		kpa = frappe.db.get_single_value("CGM Shipping Settings", "custom_kpa_free_days")
		if kpa in (None, 0):
			frappe.db.set_single_value(
				"CGM Shipping Settings", "custom_kpa_free_days", 5, update_modified=False
			)

	frappe.clear_cache(doctype="CGM Shipping Settings")


def ensure_task_container_update_fields() -> None:
	"""Task child table for per-container data entry (SL deposit + transport steps)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CONTAINER_UPDATES_DEPENDS_ON,
	)

	# Container Step stamps plus the Shipping Line deposit steps - same text as
	# custom/task.json, so migrate and the export never flip it back and forth.
	depends = CONTAINER_UPDATES_DEPENDS_ON
	for fieldname, values in (
		(
			"custom_section_container_updates",
			{
				"fieldname": "custom_section_container_updates",
				"label": "Container Updates",
				"fieldtype": "Section Break",
				"insert_after": "custom_sequence_no",
				"collapsible": 1,
				"depends_on": depends,
			},
		),
		(
			"custom_container_updates",
			{
				"fieldname": "custom_container_updates",
				"label": "Container Updates",
				"fieldtype": "Table",
				"options": "Task Container Update",
				"insert_after": "custom_section_container_updates",
				"depends_on": depends,
			},
		),
	):
		name = f"Task-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			doc = frappe.get_doc("Custom Field", name)
			if doc.depends_on != depends:
				doc.depends_on = depends
				doc.save(ignore_permissions=True)
		else:
			_create_cf("Task", values)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_not_emptied_reason",
			"label": "If containers not exiting port - reason",
			"fieldtype": "Small Text",
			"insert_after": "custom_container_updates",
			"depends_on": "eval:doc.custom_container_step == 'Book Trucks'",
			"description": (
				"Required when task is completed but no truck details are filled "
				"for any container."
			),
		},
	)
	frappe.clear_cache(doctype="Task")


def ensure_client_paid_task_fields() -> None:
	"""Finance marks the client-pays path (no company JE; verify still required, receipt optional)."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CLIENT_PAID_BY_FIELD,
		CLIENT_PAID_FIELD,
		CLIENT_PAID_ON_FIELD,
	)

	label = "Client will pay"
	description = (
		"Tick when the client settles this fee (no company Journal Entry). "
		"Finance must still verify the invoice. Receipt attachment is optional."
	)
	_ensure_cf(
		"Task",
		{
			"fieldname": CLIENT_PAID_FIELD,
			"label": label,
			"fieldtype": "Check",
			"insert_after": "custom_journal_entry",
			"description": description,
			"allow_on_submit": 0,
		},
	)
	# _ensure_cf skips label/description on existing fields — update intentionally.
	cf_name = f"Task-{CLIENT_PAID_FIELD}"
	if frappe.db.exists("Custom Field", cf_name):
		frappe.db.set_value(
			"Custom Field",
			cf_name,
			{"label": label, "description": description},
			update_modified=False,
		)
	_ensure_cf(
		"Task",
		{
			"fieldname": CLIENT_PAID_BY_FIELD,
			"label": "Client Payment Confirmed By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": CLIENT_PAID_FIELD,
			"read_only": 1,
			"depends_on": f"eval:doc.{CLIENT_PAID_FIELD}",
		},
	)
	_ensure_cf(
		"Task",
		{
			"fieldname": CLIENT_PAID_ON_FIELD,
			"label": "Client Payment Confirmed On",
			"fieldtype": "Datetime",
			"insert_after": CLIENT_PAID_BY_FIELD,
			"read_only": 1,
			"depends_on": f"eval:doc.{CLIENT_PAID_FIELD}",
		},
	)
	frappe.clear_cache(doctype="Task")


def ensure_field_officer_task_fields() -> None:
	"""Task 16 field-officer clearance tracking fields."""
	depends = "eval:doc.custom_container_step == 'Field Clearance'"
	_create_cf(
		"Task",
		{
			"fieldname": "custom_section_field_clearance",
			"label": "Field Clearance",
			"fieldtype": "Section Break",
			"insert_after": "custom_task_documents",
			"collapsible": 1,
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_verification_type",
			"label": "Verification Type",
			"fieldtype": "Select",
			"options": (
				"\nPartial Verification\n100% Verification\nDirect Release\nScanning"
			),
			"insert_after": "custom_section_field_clearance",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_verification_status",
			"label": "Verification Status",
			"fieldtype": "Select",
			"options": (
				"\nNot Started\nIn Progress\nVerification Done\nReleased by CRO"
			),
			"insert_after": "custom_verification_type",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_customs_issue",
			"label": "Customs Issues / Holds",
			"fieldtype": "Small Text",
			"description": "Any holds, queries, or issues from KRA/KEBS",
			"insert_after": "custom_verification_status",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_delivery_note_status",
			"label": "Delivery Note Status",
			"fieldtype": "Select",
			"options": "\nNot Required\nAwaiting\nIssued",
			"insert_after": "custom_customs_issue",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_coc_status",
			"label": "COC Approval Status",
			"fieldtype": "Select",
			"options": "\nNot Required\nAwaiting COC\nCOC Received\nApproved",
			"insert_after": "custom_delivery_note_status",
			"depends_on": depends,
		},
	)
	_create_cf(
		"Task",
		{
			"fieldname": "custom_verification_report_attached",
			"label": "Verification Report Attached",
			"fieldtype": "Check",
			"insert_after": "custom_coc_status",
			"depends_on": depends,
		},
	)
	frappe.clear_cache(doctype="Task")


def ensure_project_inspection_notification_fields() -> None:
	"""Project-level inspection notification status for portal + desk indicator."""
	_create_cf(
		"Project",
		{
			"fieldname": "custom_inspection_notification_status",
			"label": "Inspection Notification Status",
			"fieldtype": "Select",
			"options": "Not Notified\nNotified\nConfirmed",
			"default": "Not Notified",
			"insert_after": "custom_shipment_status",
			"read_only": 1,
			"hidden": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_inspection_notified_on",
			"label": "Inspection Notified On",
			"fieldtype": "Datetime",
			"insert_after": "custom_inspection_notification_status",
			"read_only": 1,
			"hidden": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_inspection_confirmed_on",
			"label": "Inspection Confirmed On",
			"fieldtype": "Datetime",
			"insert_after": "custom_inspection_notified_on",
			"read_only": 1,
			"hidden": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_inspection_confirmed_by",
			"label": "Inspection Confirmed By",
			"fieldtype": "Data",
			"insert_after": "custom_inspection_confirmed_on",
			"read_only": 1,
			"hidden": 1,
		},
	)
	frappe.clear_cache(doctype="Project")


def ensure_project_port_arrival_fields() -> None:
	"""Port-arrival confirmation on Project (creates container trackers; independent of Entry)."""
	_create_cf(
		"Project",
		{
			"fieldname": "custom_port_arrival_confirmed",
			"label": "Port Arrival Confirmed",
			"fieldtype": "Check",
			"insert_after": "custom_berth_phase",
			"read_only": 1,
			"default": "0",
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_port_arrival_confirmed_on",
			"label": "Port Arrival Confirmed On",
			"fieldtype": "Datetime",
			"insert_after": "custom_port_arrival_confirmed",
			"read_only": 1,
		},
	)
	_create_cf(
		"Project",
		{
			"fieldname": "custom_port_arrival_confirmed_by",
			"label": "Port Arrival Confirmed By",
			"fieldtype": "Data",
			"insert_after": "custom_port_arrival_confirmed_on",
			"read_only": 1,
		},
	)
	frappe.clear_cache(doctype="Project")


@frappe.whitelist()
def get_project_tracking_dashboard(project: str) -> dict:
	"""Data for the HTML workflow chart on Project."""
	frappe.has_permission("Project", ptype="read", doc=project, throw=True)
	doc = frappe.get_doc("Project", project)
	workflow_status = doc.get("custom_shipment_status") or "Draft"
	use_clearance_states = project_uses_clearance_workflow_states(doc)
	from cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks import (
		get_clearance_workflow_gates_for_project,
		get_clearance_workflow_states_for_project,
	)

	states = (
		get_clearance_workflow_states_for_project(doc)
		if use_clearance_states
		else list(GENERIC_WORKFLOW_STATES)
	)
	try:
		workflow_index = states.index(workflow_status)
	except ValueError:
		workflow_index = 0

	# One Task query feeds the counters, the progress derivation and both task lists.
	tasks = get_workflow_tasks_for_project(doc, limit=100)
	completed = sum(1 for t in tasks if t.status == "Completed")
	total = len(tasks) or workflow_task_count_for_project(doc)

	if use_clearance_states:
		gates = get_clearance_workflow_gates_for_project(doc)
		progress_status, progress_index = derive_workflow_progress_from_tasks(
			tasks, states=states, gates=gates
		)
		passed_states = sorted(
			derive_workflow_passed_states(tasks, states=states, gates=gates),
			key=lambda s: states.index(s) if s in states else 999,
		)
	else:
		progress_status, progress_index = derive_generic_workflow_progress(tasks)
		passed_states = []

	visible_tasks = filter_sea_tasks_for_user(tasks)
	open_tasks = [t for t in visible_tasks if t.get("status") not in ("Completed", "Cancelled")]
	first_open = open_tasks[0] if open_tasks else None
	workflow_behind = workflow_index < progress_index
	workflow_ahead = workflow_index > progress_index
	# Keep the shipment status field aligned with tasks — advance OR rewind.
	if (workflow_behind or workflow_ahead) and use_clearance_states:
		from cgm_shipping.cgm_worldwide_shipping.customizations.sea_clearance import (
			sync_project_shipment_status_from_tasks,
		)

		synced = sync_project_shipment_status_from_tasks(project)
		if synced:
			workflow_status = synced
			try:
				workflow_index = states.index(synced)
			except ValueError:
				workflow_index = progress_index
			workflow_behind = False
			workflow_ahead = False

	from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
		get_containers_for_project,
	)

	containers = get_containers_for_project(project)

	from cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation import (
		enrich_containers_with_allocation,
	)

	containers = enrich_containers_with_allocation(containers)
	containers = _enrich_containers_with_bl_deposits(doc, containers)

	berth_phase = doc.get("custom_berth_phase") or "Before Vessel Berth"
	from cgm_shipping.cgm_worldwide_shipping.customizations.project import get_project_ata

	if get_project_ata(doc) or any(
		c.get("discharging_date") or c.get("discharge_date") for c in containers
	):
		berth_phase = "After Vessel Berthed"

	def _count_status(*statuses):
		return sum(1 for c in containers if c.get("status") in statuses)

	alert_count = sum(
		1
		for c in containers
		if c.get("alert_status")
		or (c.get("demurrage_days") or 0) > 0
		or (c.get("days_outstanding") or 0) > 0
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
		CONTAINER_CLOSED_STATUSES,
		PHASE_AT_DESTINATION,
		PHASE_RELEASED,
		container_statuses_in,
	)

	# From the shared status table, so transit containers are counted too.
	released = _count_status(*container_statuses_in(PHASE_RELEASED))
	at_warehouse = _count_status(*container_statuses_in(PHASE_AT_DESTINATION))
	returned = _count_status(*CONTAINER_CLOSED_STATUSES)

	payload = {
		"current_status": progress_status,
		"current_index": progress_index,
		"passed_states": passed_states,
		"workflow_status": workflow_status,
		"workflow_index": workflow_index,
		"workflow_behind": workflow_behind,
		"workflow_ahead": workflow_ahead,
		"states": states,
		"tasks_completed": completed,
		"tasks_total": total,
		"workflow_tasks": visible_tasks,
		"sea_tasks": visible_tasks,
		"first_open_task": first_open,
		"mode": doc.get("custom_mode_of_transport"),
		"uses_clearance_states": use_clearance_states,
		"has_workflow_tasks": bool(visible_tasks or tasks),
		"task_progress_label": "clearance tasks" if use_clearance_states else "workflow tasks",
		"show_berth_phase": use_clearance_states
		and (doc.get("custom_mode_of_transport") or "").strip().lower() == "sea",
		"berth_phase": berth_phase,
		"project_reference": get_project_reference(doc) or doc.name,
		"cgm_ref_no": (doc.get("custom_cgm_ref_no") or "").strip()
		or get_project_reference(doc)
		or doc.name,
		"containers": containers,
		"container_total": len(containers),
		"containers_released": released,
		"containers_at_warehouse": at_warehouse,
		"containers_returned": returned,
		"containers_alerts": alert_count,
		"containers_overdue": sum(
			1
			for c in containers
			if c.get("status") == "Return Overdue"
			or (c.get("alert_status") or "").startswith("🚨")
		),
		"containers_pending_empty": sum(
			1
			for c in containers
			if c.get("status")
			in (
				"Released / In Transit",
				"At Warehouse",
				"Cargo Offloaded",
				"Return Overdue",
			)
		),
		"containers_in_demurrage": sum(1 for c in containers if (c.get("demurrage_days") or 0) > 0),
		"containers_in_kpa_charges": sum(1 for c in containers if (c.get("kpa_days") or 0) > 0),
		"total_demurrage_days": sum(c.get("demurrage_days") or 0 for c in containers),
		"total_kpa_days": sum(c.get("kpa_days") or 0 for c in containers),
		"total_demurrage_amount": sum(c.get("demurrage_amount") or 0 for c in containers),
		"total_kpa_amount": sum(c.get("kpa_amount") or 0 for c in containers),
		"total_detention_amount": sum(c.get("detention_amount") or 0 for c in containers),
		**_project_bl_deposit_kpis(doc),
	}
	if doc.meta.has_field("custom_inspection_notification_status"):
		payload["inspection_notification_status"] = (
			doc.get("custom_inspection_notification_status") or "Not Notified"
		).strip()
		payload["inspection_notified_on"] = doc.get("custom_inspection_notified_on")
		payload["inspection_confirmed_on"] = doc.get("custom_inspection_confirmed_on")
		payload["inspection_confirmed_by"] = doc.get("custom_inspection_confirmed_by")
	if doc.meta.has_field("custom_port_arrival_confirmed"):
		payload["port_arrival_confirmed"] = bool(doc.get("custom_port_arrival_confirmed"))
		payload["port_arrival_confirmed_on"] = doc.get("custom_port_arrival_confirmed_on")
		payload["port_arrival_confirmed_by"] = doc.get("custom_port_arrival_confirmed_by")
	return payload


def _project_bl_deposit_summary(doc) -> dict | None:
	"""Load Bill of Lading deposit fields for this project's linked BL."""
	bl_name = (doc.get("custom_bill_of_lading") or "").strip()
	if not bl_name or not frappe.db.exists("Bill of Lading", bl_name):
		return None
	meta = frappe.get_meta("Bill of Lading")
	if not meta.has_field("deposit_arrangement"):
		return None
	fields = [
		"name",
		"deposit_arrangement",
		"deposit_payer",
		"deposit_amount",
		"deposit_payment_status",
		"deposit_refund_status",
		"deposit_return_date",
	]
	fields = [f for f in fields if meta.has_field(f) or f == "name"]
	return frappe.db.get_value("Bill of Lading", bl_name, fields, as_dict=True)


def _project_bl_deposit_kpis(doc) -> dict:
	"""Project dashboard deposit KPIs from the linked Bill of Lading (0 or 1)."""
	empty = {
		"deposits_unpaid": 0,
		"deposits_paid_outstanding": 0,
		"deposits_refund_pending": 0,
	}
	bl = _project_bl_deposit_summary(doc)
	if not bl or (bl.get("deposit_arrangement") or "").strip() != "Container Deposit":
		return empty
	payment = (bl.get("deposit_payment_status") or "").strip()
	refund = (bl.get("deposit_refund_status") or "").strip()
	return {
		"deposits_unpaid": 1 if payment == "Unpaid" else 0,
		"deposits_paid_outstanding": (
			1
			if payment == "Paid" and refund not in ("Received", "Forfeited")
			else 0
		),
		"deposits_refund_pending": 1 if refund == "Pending" else 0,
	}


def _enrich_containers_with_bl_deposits(doc, containers: list[dict]) -> list[dict]:
	"""Overlay BL deposit amount (per child) + BL payment/refund status onto tracker cards."""
	bl = _project_bl_deposit_summary(doc)
	has_arrangement = bl and (bl.get("deposit_arrangement") or "").strip() == "Container Deposit"
	if not has_arrangement:
		for c in containers:
			c.setdefault("deposit_arrangement", "")
			c.setdefault("has_deposit", 0)
			c.setdefault("deposit_amount", 0)
			c.setdefault("deposit_payment_status", "")
			c.setdefault("deposit_refund_status", "")
		return containers

	bl_name = bl.name
	child_by_number = {}
	child_by_tracker = {}
	for row in frappe.get_all(
		"Container",
		filters={"parent": bl_name, "parenttype": "Bill of Lading"},
		fields=["container_number", "container_tracker", "deposit_amount"],
	):
		key = (row.container_number or "").strip().upper()
		if key:
			child_by_number[key] = row
		if row.container_tracker:
			child_by_tracker[row.container_tracker] = row

	payment = (bl.get("deposit_payment_status") or "").strip()
	refund = (bl.get("deposit_refund_status") or "").strip()
	return_date = bl.get("deposit_return_date")
	payer = (bl.get("deposit_payer") or "").strip()

	for c in containers:
		src = child_by_tracker.get(c.get("name")) or child_by_number.get(
			(c.get("container_number") or "").strip().upper()
		)
		amount = flt(src.get("deposit_amount")) if src else 0
		c["deposit_arrangement"] = "Container Deposit"
		c["has_deposit"] = 1 if amount > 0 else 0
		c["deposit_amount"] = amount
		c["deposit_payment_status"] = payment if amount > 0 else ""
		c["deposit_refund_status"] = refund if amount > 0 and payer != "Agent" else ""
		c["deposit_return_date"] = return_date if amount > 0 else None
	return containers


OBSOLETE_FINANCE_COST_PROJECT_FIELDS = (
	"custom_finance_cost_ucr",
	"custom_finance_cost_kebs",
	"custom_finance_cost_dvs",
	"custom_finance_cost_idf",
	"custom_finance_cost_port",
	"custom_finance_cost_transport",
	"custom_finance_cost_other",
	"custom_finance_cost_ledger",
	"custom_finance_cost_payment_count",
	"custom_finance_cost_last_payment_date",
	"custom_column_break_finance_cost_summary",
)


def ensure_project_finance_cost_fields() -> None:
	"""Single billed-total field on Project — create if missing; layout from desk export."""
	for fieldname in OBSOLETE_FINANCE_COST_PROJECT_FIELDS:
		_remove_cf("Project", fieldname)

	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_section_finance_cost_summary",
			"label": "Journal Entry Billing",
			"fieldtype": "Section Break",
			"insert_after": "total_purchase_cost",
			"collapsible": 0,
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_finance_cost_total",
			"label": "Total Billed Amount (via Journal Entry) - numeric",
			"fieldtype": "Currency",
			"insert_after": "custom_section_finance_cost_summary",
			"read_only": 1,
			"hidden": 1,
		},
	)
	_upsert_cf(
		"Project",
		{
			"fieldname": "custom_finance_cost_total_display",
			"label": "Total Billed Amount (via Journal Entry)",
			"fieldtype": "Data",
			"insert_after": "custom_section_finance_cost_summary",
			"read_only": 1,
			"bold": 1,
		},
	)
	frappe.clear_cache(doctype="Project")


def ensure_transit_project_fields() -> None:
	"""Project fields for container tracker mode, transit entry, and UBS permit tracking."""
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_container_tracker_mode",
			"label": "Container Tracker Mode",
			"fieldtype": "Link",
			"options": "Container Tracker Mode",
			"insert_after": "custom_shipment_type",
			"fetch_from": "custom_shipment_type.container_tracker_mode",
			"fetch_if_empty": 1,
			"in_standard_filter": 1,
			"description": "Where containers for this shipment are tracked (Mombasa, ICD, Transit, Export). Defaults from Shipment Type.",
		},
	)
	_set_cf_property(
		"custom_container_tracker_mode",
		hidden=0,
		fetch_from="custom_shipment_type.container_tracker_mode",
		fetch_if_empty=1,
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_uses_destination_entry",
			"label": "Uses Destination Entry",
			"fieldtype": "Check",
			"insert_after": "custom_shipment_type",
			"fetch_from": "custom_shipment_type.uses_destination_entry",
			"read_only": 1,
			"hidden": 1,
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_destination_entry_number",
			"label": "Destination Entry Number",
			"fieldtype": "Data",
			"insert_after": "project_type",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_ubs_permit_number",
			"label": "UBS Permit Number",
			"fieldtype": "Data",
			"insert_after": "custom_destination_entry_number",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_ubs_permit_date",
			"label": "UBS Permit Date",
			"fieldtype": "Date",
			"insert_after": "custom_ubs_permit_number",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_destination_entry_confirmed",
			"label": "Destination Entry Confirmed",
			"fieldtype": "Check",
			"insert_after": "custom_ubs_permit_date",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_uganda_release_date",
			"label": "Destination Country Release Date",
			"fieldtype": "Date",
			"insert_after": "custom_destination_entry_confirmed",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_coc_application_date",
			"label": "COC Application Date",
			"fieldtype": "Date",
			"insert_after": "custom_uganda_release_date",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)
	_ensure_cf(
		"Project",
		{
			"fieldname": "custom_eac_application_date",
			"label": "EAC Application Date",
			"fieldtype": "Date",
			"insert_after": "custom_coc_application_date",
			"depends_on": "eval:doc.custom_uses_destination_entry",
		},
	)

	if frappe.db.exists("Property Setter", "Project-project_type-hidden"):
		frappe.db.set_value("Property Setter", "Project-project_type-hidden", "value", "0")

	_backfill_project_container_tracker_modes()
	frappe.clear_cache(doctype="Project")


def _backfill_project_container_tracker_modes() -> None:
	"""Copy Shipment Type container tracker mode onto projects that are still blank."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.shipment import (
		container_tracking_mode_for_shipment_type,
	)

	if not frappe.db.has_column("Project", "custom_container_tracker_mode"):
		return

	for row in frappe.get_all(
		"Project",
		filters={
			"custom_shipment_type": ["is", "set"],
			"custom_container_tracker_mode": ["in", ("", None)],
		},
		fields=["name", "custom_shipment_type"],
		limit=500,
	):
		mode = container_tracking_mode_for_shipment_type(row.custom_shipment_type)
		if not mode:
			continue
		frappe.db.set_value(
			"Project",
			row.name,
			"custom_container_tracker_mode",
			mode,
			update_modified=False,
		)
		if frappe.db.has_column("Project", "project_type"):
			frappe.db.set_value(
				"Project", row.name, "project_type", mode, update_modified=False
			)
