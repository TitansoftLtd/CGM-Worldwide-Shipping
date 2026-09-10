"""Shared constants to avoid circular imports between domain modules."""

# Sea clearance task flow discriminator on Task.
SEA_TASK_FLOW_KEY = "SEA_IMPORT_E2E"
SEA_TRANSIT_IMPORT_TASK_FLOW_KEY = "SEA_TRANSIT_IMPORT_E2E"
SEA_TRANSIT_EXPORT_TASK_FLOW_KEY = "SEA_TRANSIT_EXPORT_E2E"
ROAD_TRANSIT_OUTBOUND_TASK_FLOW_KEY = "ROAD_TRANSIT_OUTBOUND_E2E"
ROAD_TRANSIT_INBOUND_TASK_FLOW_KEY = "ROAD_TRANSIT_INBOUND_E2E"

TRANSIT_TASK_FLOW_KEYS = frozenset(
	{
		SEA_TRANSIT_IMPORT_TASK_FLOW_KEY,
		SEA_TRANSIT_EXPORT_TASK_FLOW_KEY,
		ROAD_TRANSIT_OUTBOUND_TASK_FLOW_KEY,
		ROAD_TRANSIT_INBOUND_TASK_FLOW_KEY,
	}
)

# Project / Opportunity / Task document child-table fieldnames.
SHIPMENT_DOCUMENTS_FIELD = "custom_shipment_documents"
OPPORTUNITY_DOCUMENTS_FIELD = "custom_clients_documents"
TASK_DOCUMENTS_FIELD = "custom_task_documents"

# Project permit register and Task child tables.
PERMIT_REGISTER_FIELD = "custom_permit_register"
TASK_PERMITS_FIELD = "custom_task_permits"
TASK_FINANCE_FIELD = "custom_task_finance_lines"
PERMIT_JOURNAL_ENTRY_FIELD = "journal_entry"

# Finance confirms the client settled a payment directly (no CGM disbursement,
# so no Journal Entry / Payment Entry exists on the finance task).
CLIENT_PAID_FIELD = "custom_client_paid_directly"
CLIENT_PAID_BY_FIELD = "custom_client_paid_confirmed_by"
CLIENT_PAID_ON_FIELD = "custom_client_paid_confirmed_on"

# Intake documents required before Documents Received workflow state.
INTAKE_DOCUMENT_CODES = ("CI", "PKL")

# IDF/UCR certificate document codes. The "IDF CERT" Document Type carries the
# code "IDF Certificate" on live sites, so it must be accepted alongside the
# short codes or Create UCR (IDF) never auto-completes.
IDF_CERTIFICATE_CODES = frozenset({"IDF_CERT", "UCR_CERT", "IDF", "IDF Certificate"})

# Sea task completion requirement labels (Settings-driven; defaults for throws).
PRE_CLEARANCE_STAGE = "Pre-clearance"
POST_CLEARANCE_STAGE = "Post-clearance"
SUPPLIER_INVOICE_CODE = "SUP_INV"

# CGM Sea Import Workflow on Project (fallback when Settings has no override).
SEA_IMPORT_WORKFLOW_NAME = "CGM Sea Import Workflow"

# Opportunity pre-shipment workflow approved state.
APPROVED_WORKFLOW_STATE = "Approved"

# Quotation finance approval workflow.
QUOTATION_WORKFLOW_NAME = "CGM Quotation Approval"
QUOTATION_WORKFLOW_STATE_DRAFT = "Draft"
QUOTATION_WORKFLOW_STATE_PENDING_FINANCE = "Pending Finance Approval"
QUOTATION_WORKFLOW_STATE_APPROVED = "Approved"
QUOTATION_WORKFLOW_STATE_REJECTED = "Rejected"
QUOTATION_WORKFLOW_STATE_SHARED = "Shared with Client"
QUOTATION_SI_READY_STATES = frozenset(
	{
		QUOTATION_WORKFLOW_STATE_APPROVED,
		QUOTATION_WORKFLOW_STATE_SHARED,
	}
)

# Shipment Document final attachment review workflow (child-table state machine).
APPROVAL_STATUS_DRAFT = "Draft"
APPROVAL_STATUS_PENDING_REVIEW = "Pending Review"
APPROVAL_STATUS_APPROVED = "Approved"
APPROVAL_STATUS_REJECTED = "Rejected"
APPROVAL_WORKFLOW_ACTION_SEND = "Send for Review"
APPROVAL_WORKFLOW_ACTION_APPROVE = "Approve"
APPROVAL_WORKFLOW_ACTION_REJECT = "Reject"

FINAL_DOCUMENT_STATUS_DRAFT = APPROVAL_STATUS_DRAFT
FINAL_DOCUMENT_STATUS_PENDING_REVIEW = APPROVAL_STATUS_PENDING_REVIEW
FINAL_DOCUMENT_STATUS_APPROVED = APPROVAL_STATUS_APPROVED
FINAL_DOCUMENT_STATUS_REJECTED = APPROVAL_STATUS_REJECTED
FINAL_DOCUMENT_WORKFLOW_ACTION_SEND = APPROVAL_WORKFLOW_ACTION_SEND
FINAL_DOCUMENT_WORKFLOW_ACTION_APPROVE = APPROVAL_WORKFLOW_ACTION_APPROVE
FINAL_DOCUMENT_WORKFLOW_ACTION_REJECT = APPROVAL_WORKFLOW_ACTION_REJECT
FINAL_DOCUMENT_ATTACHMENT_FIELD = "final_attachment"
FINAL_DOCUMENT_NOTIFICATION = "CGM Shipment Document - Final Document Review"

# Sales Invoice approval workflow (Desk source of truth; distinct from Quotation).
SALES_INVOICE_WORKFLOW_NAME = "CGM Sales Invoice Approval"
SALES_INVOICE_WORKFLOW_STATE_DRAFT = "Draft"
SALES_INVOICE_WORKFLOW_STATE_PENDING = "Pending Approval"
SALES_INVOICE_WORKFLOW_STATE_APPROVED = "Approved"
SALES_INVOICE_WORKFLOW_STATE_CANCELLED = "Cancelled"
SALES_INVOICE_WORKFLOW_ACTION_SUBMIT_FOR_REVIEW = "Submit for Review"
SALES_INVOICE_WORKFLOW_ACTION_APPROVE = "Approve"
SALES_INVOICE_WORKFLOW_ACTION_REJECT = "Reject"
SALES_INVOICE_WORKFLOW_ACTION_CANCEL = "Cancel"
# Legacy — rejection now returns to Draft; kept for migration/backward imports only.
SALES_INVOICE_WORKFLOW_STATE_REJECTED = "Rejected"
# Backward-compatible alias for older imports.
SALES_INVOICE_WORKFLOW_STATE_PENDING_FINANCE = SALES_INVOICE_WORKFLOW_STATE_PENDING
# Approve sets this state then submits; ERPNext then owns Sales Invoice.status.
SALES_INVOICE_SUBMITTABLE_STATES = frozenset({SALES_INVOICE_WORKFLOW_STATE_APPROVED})
SALES_INVOICE_APPROVED_BY_FIELD = "custom_approved_by"
SALES_INVOICE_REJECTED_BY_FIELD = "custom_rejected_by"
SALES_INVOICE_REJECTION_REASON_FIELD = "custom_rejection_reason"

# Customer attach field → Document Type code (until Settings child table exists).
CUSTOMER_ATTACH_TO_DOCUMENT_CODE = {
	"custom_kra_pin_attachment": "KRA_PIN",
}

# Transport documents that can attach to an Opportunity shipment intake.
# Label keys match Shipment Type.transport_documents Select options.
TRANSPORT_DOCUMENT_REGISTRY: dict[str, dict[str, str | None]] = {
	"Bill of Lading": {
		"doctype": "Bill of Lading",
		"opp_field": "custom_bill_of_lading",
	},
	"Air Waybill": {
		"doctype": "Air Waybill",
		"opp_field": "custom_air_waybill",
	},
	"Booking Confirmation": {
		"doctype": "Booking Confirmation",
		"opp_field": "custom_booking_confirmation",
	},
	"Release Order": {
		"doctype": "Release Order",
		"opp_field": None,
	},
}

OPPORTUNITY_TRANSPORT_BACK_LINK_FIELD = "linked_opportunity"

# Doctypes with soft back-link to Opportunity via linked_opportunity.
BACK_LINKED_DOCTYPES = tuple(
	cfg["doctype"]
	for cfg in TRANSPORT_DOCUMENT_REGISTRY.values()
	if cfg.get("opp_field")
)

# Map template labels or old department names → ERPNext department_name stem.
DEPARTMENT_NAME_ALIASES = {
	"Administration": "Documentation",
}

# Container lifecycle operational status (derived from dates only).
CONTAINER_STATUS_PENDING_ARRIVAL = "Pending Arrival"
CONTAINER_STATUS_VESSEL_BERTHED = "Vessel Berthed"
CONTAINER_STATUS_DISCHARGED_AT_PORT = "Discharged / At Port"
CONTAINER_STATUS_RELEASED_IN_TRANSIT = "Released / In Transit"
CONTAINER_STATUS_AT_WAREHOUSE = "At Warehouse"
CONTAINER_STATUS_CARGO_OFFLOADED = "Cargo Offloaded"
CONTAINER_STATUS_EMPTY_RETURNED = "Empty Returned"
CONTAINER_STATUS_INTERCHANGE = "Interchange Received"
CONTAINER_STATUS_RETURN_OVERDUE = "Return Overdue"

# Legacy aliases (reports / portal may still reference these strings).
CONTAINER_STATUS_AT_PORT = CONTAINER_STATUS_DISCHARGED_AT_PORT
CONTAINER_STATUS_AWAITING_DISCHARGE = CONTAINER_STATUS_VESSEL_BERTHED
CONTAINER_STATUS_DISPATCHED = CONTAINER_STATUS_RELEASED_IN_TRANSIT
CONTAINER_STATUS_DELIVERED = CONTAINER_STATUS_AT_WAREHOUSE
CONTAINER_STATUS_EMPTY_PENDING = CONTAINER_STATUS_CARGO_OFFLOADED
CONTAINER_STATUS_OVERDUE = CONTAINER_STATUS_RETURN_OVERDUE

# Every container status, and what each view does with it. All status lists in
# the app are generated from this table, so a status the derivers start
# returning only needs a row here to be coloured, counted and return-tracked.
# Transit statuses used to exist only inside _derive_transit_status, so every
# downstream list silently ignored transit containers.
#
#   phase   lifecycle stage - drives the Project tab counts and return tracking
#   colour  Desk indicator colour (tracker form, report, Project tab)
#   pill    Ops Board pill tone
#
# Colour rule: unchanged before offloading, orange once the offloading date is
# recorded, green only when the interchange is confirmed. Return Overdue stays
# red - it is a live demurrage alarm and must not blend in.
PHASE_AWAITING = "awaiting"  # not at port yet, or outbound not loaded
PHASE_AT_PORT = "at_port"
PHASE_RELEASED = "released"  # out of port, on the road / in transit
PHASE_AT_DESTINATION = "at_destination"  # warehouse or destination, offloaded or not
PHASE_OVERDUE = "overdue"
PHASE_RETURNED = "returned"  # empty back, interchange not yet confirmed
PHASE_COMPLETE = "complete"  # interchange confirmed

CONTAINER_STATUS_TABLE = (
	# (status, phase, colour, pill)
	(CONTAINER_STATUS_PENDING_ARRIVAL, PHASE_AWAITING, "gray", "muted"),
	(CONTAINER_STATUS_VESSEL_BERTHED, PHASE_AT_PORT, "yellow", "info"),
	(CONTAINER_STATUS_DISCHARGED_AT_PORT, PHASE_AT_PORT, "yellow", "warning"),
	("KRA Released", PHASE_AT_PORT, "yellow", "warning"),
	(CONTAINER_STATUS_RELEASED_IN_TRANSIT, PHASE_RELEASED, "orange", "primary"),
	("Released from Port", PHASE_RELEASED, "orange", "primary"),
	("Release Order Obtained", PHASE_RELEASED, "orange", "primary"),
	("Loading Slip Received", PHASE_RELEASED, "orange", "primary"),
	("Delivery Note Ready", PHASE_RELEASED, "orange", "primary"),
	("C2 Obtained", PHASE_RELEASED, "orange", "primary"),
	("Departed / ECMD Active", PHASE_RELEASED, "orange", "primary"),
	("In Transit", PHASE_RELEASED, "orange", "primary"),
	("Border Cleared", PHASE_RELEASED, "orange", "primary"),
	(CONTAINER_STATUS_AT_WAREHOUSE, PHASE_AT_DESTINATION, "blue", "primary"),
	("Arrived at Destination", PHASE_AT_DESTINATION, "blue", "primary"),
	(CONTAINER_STATUS_CARGO_OFFLOADED, PHASE_AT_DESTINATION, "orange", "active"),
	("Offloaded at Destination", PHASE_AT_DESTINATION, "orange", "active"),
	(CONTAINER_STATUS_RETURN_OVERDUE, PHASE_OVERDUE, "red", "danger"),
	(CONTAINER_STATUS_EMPTY_RETURNED, PHASE_RETURNED, "orange", "active"),
	(CONTAINER_STATUS_INTERCHANGE, PHASE_COMPLETE, "green", "success"),
	# Outbound transit, before the box is loaded.
	("Pending Loading", PHASE_AWAITING, "gray", "muted"),
	("Loading at Warehouse", PHASE_AWAITING, "yellow", "warning"),
)


def container_statuses_in(*phases: str) -> frozenset[str]:
	"""Every status in the given lifecycle phases."""
	return frozenset(status for status, phase, _c, _p in CONTAINER_STATUS_TABLE if phase in phases)


CONTAINER_STATUS_COLOUR = {status: colour for status, _ph, colour, _p in CONTAINER_STATUS_TABLE}
CONTAINER_STATUS_PILL = {status: pill for status, _ph, _c, pill in CONTAINER_STATUS_TABLE}

# Charges stop and the container leaves the active lists.
CONTAINER_CLOSED_STATUSES = container_statuses_in(PHASE_RETURNED, PHASE_COMPLETE)
# Out of port with the return cycle still open (includes awaiting interchange).
CONTAINER_RETURN_OPEN_STATUSES = container_statuses_in(
	PHASE_RELEASED, PHASE_AT_DESTINATION, PHASE_OVERDUE, PHASE_RETURNED
)
# Out of port and the empty is not back yet.
CONTAINER_EMPTY_PENDING_STATUSES = container_statuses_in(
	PHASE_RELEASED, PHASE_AT_DESTINATION, PHASE_OVERDUE
)

# Statuses whose current_location is re-derived on every save. Port-side only on
# purpose: derive_current_location does not model the transit legs, so transit
# containers keep the location that was entered for them.
CONTAINER_LOCATION_REFRESH_STATUSES = frozenset(
	{
		CONTAINER_STATUS_VESSEL_BERTHED,
		CONTAINER_STATUS_DISCHARGED_AT_PORT,
		CONTAINER_STATUS_RELEASED_IN_TRANSIT,
		CONTAINER_STATUS_AT_WAREHOUSE,
		CONTAINER_STATUS_CARGO_OFFLOADED,
	}
)


def container_status_boot() -> dict:
	"""The table as the Desk reads it (frappe.boot.cgm_container_statuses)."""
	return {
		"order": [status for status, *_ in CONTAINER_STATUS_TABLE],
		"statuses": {
			status: {
				"phase": phase,
				"colour": colour,
				"pill": pill,
				"return_open": status in CONTAINER_RETURN_OPEN_STATUSES,
				"closed": status in CONTAINER_CLOSED_STATUSES,
			}
			for status, phase, colour, pill in CONTAINER_STATUS_TABLE
		},
	}

# Shipment status (Project.custom_shipment_status) - one row per status, in chart
# order: (status, customer milestone, Desk tone, portal tone). The Select options
# on Project list the same statuses in the same order (tests pin it), and every
# workflow gate table must use these names. The Desk and portal colours differ
# today; to unify them, make the two tone columns agree here.
SHIPMENT_MILESTONES = (
	"Booking & Documents",
	"Pre-Clearance",
	"In Transit",
	"Arrival & Customs Entry",
	"Clearance",
	"Delivery",
)

SHIPMENT_STATUS_TABLE = (
	("Draft", "Booking & Documents", "muted", "muted"),
	("Documents Received", "Booking & Documents", "primary", "active"),
	("UCR Applied", "Booking & Documents", "primary", "active"),
	("UCR Paid", "Booking & Documents", "primary", "active"),
	("Pre-clearance", "Pre-Clearance", "primary", "active"),
	("Client Inspection", "Pre-Clearance", "info", "active"),
	("In Transit", "In Transit", "info", "info"),
	("Final Docs Received", "Arrival & Customs Entry", "primary", "active"),
	("Entry Lodged", "Arrival & Customs Entry", "primary", "active"),
	("Line Paid & DO Lodged", "Arrival & Customs Entry", "warning", "active"),
	("Entry Paid", "Arrival & Customs Entry", "warning", "active"),
	("Post-clearance", "Clearance", "primary", "active"),
	("Field Clearance", "Clearance", "primary", "active"),
	("KPA Paid", "Clearance", "warning", "active"),
	("In Delivery", "Delivery", "info", "info"),
	("Containers Returned", "Delivery", "primary", "primary"),
	("Completed", "Delivery", "success", "success"),
)

SHIPMENT_STATUSES = tuple(row[0] for row in SHIPMENT_STATUS_TABLE)
_SHIPMENT_STATUS_ROWS = {row[0]: row for row in SHIPMENT_STATUS_TABLE}


def shipment_status_tone(status: str | None, *, portal: bool = False) -> str:
	"""Pill tone for a shipment status; unknown statuses read as in progress."""
	if not status:
		return "muted"
	row = _SHIPMENT_STATUS_ROWS.get(status)
	if not row:
		return "active"
	return row[3] if portal else row[2]


def shipment_status_boot() -> dict:
	"""The shipment status table for the Desk, via frappe.boot."""
	return {
		"order": list(SHIPMENT_STATUSES),
		"statuses": {
			status: {"milestone": milestone, "tone": desk, "portal_tone": portal}
			for status, milestone, desk, portal in SHIPMENT_STATUS_TABLE
		},
	}


# Sequence numbers for the container lifecycle steps. Each key is a field on CGM
# Shipping Settings ("Container tracking tasks"), where 0 means "use the value
# below". Read them through get_container_task_sequence(), never from this dict
# directly, or a changed Setting is silently ignored.
CONTAINER_TASK_SEQ_DEFAULTS: dict[str, int] = {
	# Documents checkpoint. Completing it pushes the Project ETA onto every
	# container tracker; this is not a separate "track ETA" step (that was
	# retired from the template - the Settings field kept its name).
	"custom_track_eta_task_seq": 8,
	# Bulk vessel-arrival event key used by Project port-arrival confirm.
	# Not tied to Create Entry - Entry is paperwork-only.
	"custom_vessel_arrival_task_seq": 12,
	"custom_field_clearance_task_seq": 17,
	"custom_kpa_paid_task_seq": 19,
	"custom_book_trucks_task_seq": 20,
	"custom_gate_out_task_seq": 21,
	"custom_monitor_delivery_task_seq": 22,
	"custom_offload_task_seq": 23,
	"custom_empty_return_task_seq": 24,
	"custom_interchange_task_seq": 25,
}

# Task fields used to identify a single container for container-specific lifecycle events.
TASK_CONTAINER_TRACKER_FIELD = "custom_container_tracker"
TASK_CONTAINER_NUMBER_FIELD = "custom_container_number"
TASK_CARGO_TYPE_FIELD = "custom_cargo_type"

# Task child table for per-container data entry (transport / field clearance / KPA).
# Seq 12 (Create Entry / vessel-arrival) is a Project→Task mirror only - not a
# completion gate.
TASK_CONTAINER_UPDATES_FIELD = "custom_container_updates"
# Settings fields for the steps that show the grid: every container step except
# the ETA refresh. Base set only - the grid also shows on the shipping line
# application / finance steps, so use
# task_container_updates.container_update_task_sequences() for the full set.
CONTAINER_UPDATE_TASK_SEQ_FIELDS = tuple(
	fieldname for fieldname in CONTAINER_TASK_SEQ_DEFAULTS if fieldname != "custom_track_eta_task_seq"
)

# Settings fieldnames - bulk events update every tracker on the project.
BULK_CONTAINER_TASK_SEQ_FIELDS = (
	"custom_track_eta_task_seq",
	"custom_vessel_arrival_task_seq",
	"custom_field_clearance_task_seq",
	"custom_kpa_paid_task_seq",
	"custom_book_trucks_task_seq",
)

# Settings fieldnames — require a single-container identifier on the Task.
CONTAINER_SPECIFIC_TASK_SEQ_FIELDS = (
	"custom_gate_out_task_seq",
	"custom_monitor_delivery_task_seq",
	"custom_offload_task_seq",
	"custom_empty_return_task_seq",
	"custom_interchange_task_seq",
)

# Container lifecycle steps: CGM Task Template Item "Container Step", stamped on
# Task as custom_container_step. The stamp decides which container event a task
# records - its own step number does not, so moving template rows cannot misroute
# one. Keyed by the Settings field that used to identify each step by number;
# that number is now only an internal key and the fallback for Sea Import tasks
# created before the stamp existed.
CONTAINER_STEP_ETA_REFRESH = "ETA Refresh"
CONTAINER_STEP_VESSEL_ARRIVAL = "Vessel Arrival"
CONTAINER_STEP_FIELD_CLEARANCE = "Field Clearance"
CONTAINER_STEP_KPA_PAID = "KPA Paid"
CONTAINER_STEP_BOOK_TRUCKS = "Book Trucks"
CONTAINER_STEP_GATE_OUT = "Gate Out"
CONTAINER_STEP_MONITOR_DELIVERY = "Monitor Delivery"
CONTAINER_STEP_OFFLOAD = "Offload"
CONTAINER_STEP_EMPTY_RETURN = "Empty Return"
CONTAINER_STEP_INTERCHANGE = "Interchange"

CONTAINER_STEP_BY_SEQ_FIELD: dict[str, str] = {
	"custom_track_eta_task_seq": CONTAINER_STEP_ETA_REFRESH,
	"custom_vessel_arrival_task_seq": CONTAINER_STEP_VESSEL_ARRIVAL,
	"custom_field_clearance_task_seq": CONTAINER_STEP_FIELD_CLEARANCE,
	"custom_kpa_paid_task_seq": CONTAINER_STEP_KPA_PAID,
	"custom_book_trucks_task_seq": CONTAINER_STEP_BOOK_TRUCKS,
	"custom_gate_out_task_seq": CONTAINER_STEP_GATE_OUT,
	"custom_monitor_delivery_task_seq": CONTAINER_STEP_MONITOR_DELIVERY,
	"custom_offload_task_seq": CONTAINER_STEP_OFFLOAD,
	"custom_empty_return_task_seq": CONTAINER_STEP_EMPTY_RETURN,
	"custom_interchange_task_seq": CONTAINER_STEP_INTERCHANGE,
}
CONTAINER_STEPS = tuple(CONTAINER_STEP_BY_SEQ_FIELD.values())
# Steps whose task shows the Task Container Updates grid (all but the ETA refresh).
CONTAINER_UPDATE_STEPS = tuple(s for s in CONTAINER_STEPS if s != CONTAINER_STEP_ETA_REFRESH)
# Transport runs in parallel: these steps do not hold each other up on a status gate.
TRANSPORT_CONTAINER_STEPS = (
	CONTAINER_STEP_BOOK_TRUCKS,
	CONTAINER_STEP_GATE_OUT,
	CONTAINER_STEP_MONITOR_DELIVERY,
	CONTAINER_STEP_OFFLOAD,
	CONTAINER_STEP_EMPTY_RETURN,
	CONTAINER_STEP_INTERCHANGE,
)

# Task form depends_on for the container grid. custom/task.json carries the same
# text, and project_layout.ensure_task_container_update_fields writes it on
# migrate - tests pin that they agree.
CONTAINER_UPDATES_DEPENDS_ON = (
	"eval:['Sea Import Workflow','SEA_IMPORT_E2E'].includes(doc.custom_task_flow_key) && ("
	"[" + ",".join(f"'{s}'" for s in CONTAINER_UPDATE_STEPS) + "].includes(doc.custom_container_step)"
	" || (['Application','Finance Payment'].includes(doc.custom_task_role)"
	" && doc.custom_payment_kind == 'Shipping Line'))"
)

DEPOSIT_REFUND_STATUSES = (
	"Pending",
	"Applied",
	"Received",
	"Forfeited",
)

DEPOSIT_PAYMENT_STATUSES = (
	"Not Applicable",
	"Unpaid",
	"Paid",
)

DEPOSIT_ARRANGEMENT_CONTAINER = "Container Deposit"
DEPOSIT_ARRANGEMENT_REVOLVING = "Revolving Fund"
DEPOSIT_ARRANGEMENTS = (
	DEPOSIT_ARRANGEMENT_CONTAINER,
	DEPOSIT_ARRANGEMENT_REVOLVING,
)

DEPOSIT_PAYERS = (
	"Agent",
	"Customer",
	"Company",
)

# High-level cargo classification (distinct from Container Type size masters).
CARGO_TYPE_OPTIONS = (
	"FCL",
	"LCL",
	"Breakbulk",
	"Project Cargo",
)

# ERPNext Notification names (ensured by patches.ensure_sea_task_notifications).
FINANCE_PAYMENT_ACTION = "CGM Task - Finance Payment Action"
PERMIT_INVOICES_TO_FINANCE = "CGM Task - Permit Invoices to Finance"
PERMIT_RECEIPTS_FOR_DECLARANT = "CGM Task - Permit Receipts for Declarant"
PERMIT_RECEIPTS_VERIFY_FINANCE = "CGM Task - Permit Receipts Verify Finance"
UCR_INVOICE_TO_FINANCE = "CGM Task - UCR Invoice to Finance"
UCR_RECEIPT_FOR_DECLARANT = "CGM Task - UCR Receipt for Declarant"
UCR_RECEIPT_VERIFY_FINANCE = "CGM Task - UCR Receipt Verify Finance"
ENTRY_INVOICE_TO_FINANCE = "CGM Task - Entry Invoice to Finance"
ENTRY_RECEIPT_FOR_DECLARANT = "CGM Task - Entry Receipt for Declarant"
ENTRY_RECEIPT_VERIFY_FINANCE = "CGM Task - Entry Receipt Verify Finance"
SHIPPING_LINE_INVOICE_TO_FINANCE = "CGM Task - Shipping Line Invoice to Finance"
SHIPPING_LINE_RECEIPT_FOR_DECLARANT = "CGM Task - Shipping Line Receipt for Declarant"
SHIPPING_LINE_RECEIPT_VERIFY_FINANCE = "CGM Task - Shipping Line Receipt Verify Finance"
KPA_INVOICE_TO_FINANCE = "CGM Task - KPA Invoice to Finance"
KPA_RECEIPT_FOR_SUPERVISOR = "CGM Task - KPA Receipt for Supervisor"
KPA_RECEIPT_VERIFY_FINANCE = "CGM Task - KPA Receipt Verify Finance"
DAILY_STATUS_RAG_ALERT = "CGM Daily Status - RAG Alert"
TRANSPORTER_TRUCK_UPDATE = "CGM Operational Update"  # legacy alias
OPERATIONAL_UPDATE_NOTIFICATION = "CGM Operational Update"
CONTAINER_DEPOSIT_REFUND_REMINDER = "CGM Container - Deposit Refund Reminder"
PORTAL_UPDATE_PUBLISHED_NOTIFICATION = "CGM Portal - Update Published"
PORTAL_FEEDBACK_NOTIFICATION = "CGM Portal - Feedback Received"

# Per-row decisions on Funding Request Material Request child table.
FR_ROW_DECISION_PENDING = "Pending"
FR_ROW_DECISION_APPROVED = "Approved"
FR_ROW_DECISION_REJECTED = "Rejected"

# ── Material Request workflow (separate DocType/workflow — configured in ERPNext) ──

MR_WORKFLOW_STATE_FIELD = "workflow_state"
MR_WORKFLOW_STATE_DRAFT = "Draft"
MR_WORKFLOW_STATE_SUBMITTED = "Submitted"
MR_WORKFLOW_STATE_UNFUNDED = "Unfunded"
MR_WORKFLOW_STATE_ON_FUNDING_REQUEST = "On Funding Request"
MR_WORKFLOW_STATE_APPROVED = "Approved"
MR_WORKFLOW_STATE_DISBURSED = "Disbursed"
MR_WORKFLOW_STATE_REJECTED = "Rejected"
MR_WORKFLOW_STATE_CANCELLED = "Cancelled"

MATERIAL_REQUEST_TYPE_OPERATIONAL = "Operational Expense"

# Standard Task fields hidden on sea clearance tasks live in SEA_TASK_HIDDEN_FIELDS
# in public/js/task.js — hiding is a form concern and only the desk applies it.
# A second copy here was never imported and had already drifted from that list.

# Sales Invoice numbering: INV-MMYY-#### / CR-MMYY-#### (MMYY = month+year from posting date).
SALES_INVOICE_NAMING_SERIES = "INV-.MMYY.-.####"
SALES_INVOICE_CREDIT_NOTE_NAMING_SERIES = "CR-.MMYY.-.####"
