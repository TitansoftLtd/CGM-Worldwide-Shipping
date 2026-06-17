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
