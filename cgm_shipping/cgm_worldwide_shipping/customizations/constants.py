"""Shared constants to avoid circular imports between domain modules."""

# Sea clearance task flow discriminator on Task.
SEA_TASK_FLOW_KEY = "SEA_IMPORT_E2E"

# Project / Opportunity / Task document child-table fieldnames.
SHIPMENT_DOCUMENTS_FIELD = "custom_shipment_documents"
OPPORTUNITY_DOCUMENTS_FIELD = "custom_clients_documents"
TASK_DOCUMENTS_FIELD = "custom_task_documents"

# Project permit register and Task child tables.
PERMIT_REGISTER_FIELD = "custom_permit_register"
TASK_PERMITS_FIELD = "custom_task_permits"
TASK_FINANCE_FIELD = "custom_task_finance_lines"

# Intake documents required before Documents Received workflow state.
INTAKE_DOCUMENT_CODES = ("CI", "PKL")

# Sea task completion requirement labels (Settings-driven; defaults for throws).
PRE_CLEARANCE_STAGE = "Pre-clearance"
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

# Customer attach field → Document Type code (until Settings child table exists).
CUSTOMER_ATTACH_TO_DOCUMENT_CODE = {
	"custom_kra_pin_attachment": "KRA_PIN",
}

# Doctypes with soft back-link to Opportunity via linked_opportunity.
BACK_LINKED_DOCTYPES = ("Air Waybill", "Bill of Lading")

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
	"custom_vessel_arrival_task_seq": 11,
	"custom_field_clearance_task_seq": 16,
	"custom_kpa_paid_task_seq": 18,
	"custom_book_trucks_task_seq": 19,
	"custom_gate_out_task_seq": 20,
	"custom_monitor_delivery_task_seq": 21,
	"custom_offload_task_seq": 22,
	"custom_empty_return_task_seq": 23,
	"custom_interchange_task_seq": 24,
}

# Backward-compatible aliases.
TASK_SEQ_LOAD_AND_EXIT_PORT = CONTAINER_TASK_SEQ_DEFAULTS["custom_gate_out_task_seq"]
TASK_SEQ_EMPTY_RETURN = CONTAINER_TASK_SEQ_DEFAULTS["custom_empty_return_task_seq"]

# Task fields used to identify a single container for container-specific lifecycle events.
TASK_CONTAINER_TRACKER_FIELD = "custom_container_tracker"
TASK_CONTAINER_NUMBER_FIELD = "custom_container_number"
TASK_TYPE_OF_CONTAINER_FIELD = "custom_type_of_container"

# Task child table for per-container data entry (tasks 11, 16, 18–24).
TASK_CONTAINER_UPDATES_FIELD = "custom_container_updates"
CONTAINER_UPDATE_TASK_SEQS = frozenset({11, 16, 18, 19, 20, 21, 22, 23, 24})
CONTAINER_UPDATE_SEED_SEQS = frozenset({11, 16, 18, 19, 20, 21, 22, 23, 24})

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

# ERPNext Notification fixture names (see fixtures/notification.json).
FINANCE_PAYMENT_ACTION = "CGM Task - Finance Payment Action"
PERMIT_INVOICES_TO_FINANCE = "CGM Task - Permit Invoices to Finance"
PERMIT_RECEIPTS_FOR_DECLARANT = "CGM Task - Permit Receipts for Declarant"
PERMIT_RECEIPTS_VERIFY_FINANCE = "CGM Task - Permit Receipts Verify Finance"
UCR_INVOICE_TO_FINANCE = "CGM Task - UCR Invoice to Finance"
UCR_RECEIPT_FOR_DECLARANT = "CGM Task - UCR Receipt for Declarant"
UCR_RECEIPT_VERIFY_FINANCE = "CGM Task - UCR Receipt Verify Finance"
DAILY_STATUS_RAG_ALERT = "CGM Daily Status - RAG Alert"

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
