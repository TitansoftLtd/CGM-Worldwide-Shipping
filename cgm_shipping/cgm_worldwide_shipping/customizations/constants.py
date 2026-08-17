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
SALES_INVOICE_WORKFLOW_STATE_REJECTED = "Rejected"
SALES_INVOICE_WORKFLOW_ACTION_SUBMIT_FOR_REVIEW = "Submit for Review"
SALES_INVOICE_WORKFLOW_ACTION_APPROVE = "Approve"
SALES_INVOICE_WORKFLOW_ACTION_REJECT = "Reject"
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

# Fallback sequence numbers used when CGM Shipping Settings fields are
# not yet configured. Configure in CGM Shipping Settings → Container
# tracking tasks to override these.
CONTAINER_TASK_SEQ_DEFAULTS: dict[str, int] = {
	"custom_track_eta_task_seq": 8,
	# Bulk vessel-arrival event key used by Project port-arrival confirm.
	# Not tied to Create Entry — Entry is paperwork-only.
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

# Backward-compatible aliases.
TASK_SEQ_LOAD_AND_EXIT_PORT = CONTAINER_TASK_SEQ_DEFAULTS["custom_gate_out_task_seq"]
TASK_SEQ_EMPTY_RETURN = CONTAINER_TASK_SEQ_DEFAULTS["custom_empty_return_task_seq"]

# Task fields used to identify a single container for container-specific lifecycle events.
TASK_CONTAINER_TRACKER_FIELD = "custom_container_tracker"
TASK_CONTAINER_NUMBER_FIELD = "custom_container_number"
TASK_CARGO_TYPE_FIELD = "custom_cargo_type"

# Task child table for per-container data entry (transport / field clearance / KPA).
# Seq 12 (Create Entry / vessel-arrival) is a Project→Task mirror only — not a
# completion gate.
TASK_CONTAINER_UPDATES_FIELD = "custom_container_updates"
CONTAINER_UPDATE_TASK_SEQS = frozenset({12, 17, 19, 20, 21, 22, 23, 24, 25})
CONTAINER_UPDATE_SEED_SEQS = frozenset({12, 17, 19, 20, 21, 22, 23, 24, 25})
TRANSPORT_TASK_SEQS = frozenset({21, 22, 23, 24, 25, 26})

# Settings fieldnames — bulk events update every tracker on the project.
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

# Funding Request workflow (Director approval gate — not an accounting voucher).
DIRECTOR_ROLE = "Director"
FUNDING_REQUEST_WORKFLOW_NAME = "CGM Funding Request Approval"
FUNDING_REQUEST_STATE_DRAFT = "Draft"
FUNDING_REQUEST_STATE_PENDING = "Pending Director Approval"
FUNDING_REQUEST_STATE_APPROVED = "Director Approved"
FUNDING_REQUEST_STATE_FUNDING = "Funding in Progress"
FUNDING_REQUEST_STATE_FUNDED = "Funded"
FUNDING_REQUEST_STATE_COMPLETED = "Completed"
FUNDING_REQUEST_STATE_REJECTED = "Rejected"
FUNDING_REQUEST_STATE_CANCELLED = "Cancelled"
FUNDING_REQUEST_ACTION_SUBMIT = "Submit for Director Approval"
FUNDING_REQUEST_ACTION_APPROVE = "Approve"
FUNDING_REQUEST_ACTION_REJECT = "Reject"
FUNDING_REQUEST_ACTION_START_FUNDING = "Start Funding"
FUNDING_REQUEST_ACTION_MARK_FUNDED = "Mark Funded"
FUNDING_REQUEST_ACTION_COMPLETE = "Complete"
FUNDING_REQUEST_ACTION_CANCEL = "Cancel"
FUNDING_REQUEST_APPROVED_STATES = frozenset(
	{
		FUNDING_REQUEST_STATE_APPROVED,
		FUNDING_REQUEST_STATE_FUNDING,
		FUNDING_REQUEST_STATE_FUNDED,
		FUNDING_REQUEST_STATE_COMPLETED,
	}
)

# Material Request funding workflow. Reuses the same Workflow State masters as
# Funding Request where the names already match (Pending / Approved / Funded / Rejected).
MR_FUNDING_WORKFLOW_NAME = "CGM Material Request Funding"
MR_FUNDING_WORKFLOW_STATE_FIELD = "workflow_state"
MR_FUNDING_STATE_DRAFT = "Draft"
MR_FUNDING_STATE_SUBMITTED = "Submitted"
MR_FUNDING_STATE_UNFUNDED = "Unfunded"
MR_FUNDING_STATE_ON_REQUEST = "On Funding Request"
MR_FUNDING_STATE_PENDING = FUNDING_REQUEST_STATE_PENDING
MR_FUNDING_STATE_APPROVED = FUNDING_REQUEST_STATE_APPROVED
MR_FUNDING_STATE_FUNDED = FUNDING_REQUEST_STATE_FUNDED
MR_FUNDING_STATE_REJECTED = FUNDING_REQUEST_STATE_REJECTED
MR_FUNDING_STATE_CANCELLED = FUNDING_REQUEST_STATE_CANCELLED
MR_FUNDING_ACTION_SUBMIT = "Submit"
MR_FUNDING_ACTION_SUBMIT_REQUEST = "Submit Request"
MR_FUNDING_ACTION_CANCEL = FUNDING_REQUEST_ACTION_CANCEL
MATERIAL_REQUEST_TYPE_OPERATIONAL = "Operational Expense"

# Standard Task fields to hide on all sea clearance tasks (reduce noise).
SEA_TASK_HIDDEN_FIELDS = (
	"is_template",
	"issue",
	"type",
	"color",
	"is_milestone",
	"task_weight",
	"exp_start_date",
	"exp_end_date",
	"expected_time",
	"duration",
	"progress",
	"total_costing_amount",
	"total_billing_amount",
	"total_expense_claim",
	"review_date",
	"closing_date",
	"template_tasks",
)
