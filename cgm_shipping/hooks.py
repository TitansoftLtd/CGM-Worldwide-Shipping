app_name = "cgm_shipping"
app_title = "CGM Worldwide Shipping"
app_publisher = "Titansoft Limited"
app_description = "CGM Customizations"
app_email = "nkubitudouglas@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "cgm_shipping",
# 		"logo": "/assets/cgm_shipping/logo.png",
# 		"title": "CGM Worldwide Shipping",
# 		"route": "/cgm_shipping",
# 		"has_permission": "cgm_shipping.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = [
	"/assets/cgm_shipping/css/project_tracking.css",
	"/assets/cgm_shipping/css/operational_updates.css",
	"/assets/cgm_shipping/css/opportunity_intake_wizard.css",
	"/assets/cgm_shipping/css/cgm_shipping_workspace.css",
]
app_include_js = [
	# Must load before cgm_status_field.js — status grids call attach helpers from this file.
	"/assets/cgm_shipping/js/shipment_document_grid.js",
	"/assets/cgm_shipping/js/cgm_status_field.js",
	"/assets/cgm_shipping/js/cgm_container_tracking.js",
	"/assets/cgm_shipping/js/operational_updates_ui.js",
	"/assets/cgm_shipping/js/cgm_shipping_workspace.js",
	"/assets/cgm_shipping/js/supplier_link_filters.js",
]

# include js, css files in header of web template
# Customer portal: shared design-system CSS + browser-side timezone
# localization for the /portal, /my-shipments, /shipment and /documents pages.
web_include_css = [
	"/assets/cgm_shipping/css/customer_portal.css",
	"/assets/cgm_shipping/css/operational_updates.css",
]
web_include_js = [
	"/assets/cgm_shipping/js/portal_localize_time.js",
	"/assets/cgm_shipping/js/operational_updates_ui.js",
]

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "cgm_shipping/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"CGM Task Template": "public/js/cgm_task_template.js",
	"Task": [
		"public/js/cgm_status_field.js",
		"public/js/shipment_document_grid.js",
		"public/js/attachment_approval_workflow.js",
		"public/js/task.js",
	],
	"Purchase Invoice": "public/js/purchase_invoice.js",
	"Project": [
		"public/js/shipment_document_grid.js",
		"public/js/attachment_approval_workflow.js",
		"public/js/cgm_transport_reference.js",
		"public/js/cgm_bl_containers.js",
		"public/js/project.js",
	],
	"Lead": [
		"public/js/cgm_transport_reference.js",
		"public/js/cgm_bl_containers.js",
		"public/js/crm_lead.js",
	],
	"Customer": "public/js/crm_customer.js",
	"Item": "public/js/item_pricing_rule.js",
	"Opportunity": [
		"public/js/opportunity_shipment.js",
		"public/js/cgm_transport_reference.js",
		"public/js/cgm_bl_containers.js",
		"public/js/shipment_document_grid.js",
		"public/js/attachment_approval_workflow.js",
		"public/js/crm_opportunity.js",
		"public/js/opportunity.js",
	],
	"Quotation": "public/js/quotation.js",
	"Sales Invoice": "public/js/sales_invoice.js",
	"Supplier": "public/js/supplier.js",
	"Leave Application": "public/js/leave_application.js",
	"Bill of Lading": "public/js/cgm_transport_reference.js",
	"Material Request": "public/js/material_request.js",
	"Employee Advance": "public/js/employee_advance.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
doctype_list_js = {
	"Task": "public/js/task_list.js",
	"Material Request": "public/js/material_request_list.js",
}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "cgm_shipping/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# Customers (Website Users) land on the branded shipment portal.
role_home_page = {
    "Customer": "portal",
    "Transporter": "transporter",
}

get_website_user_home_page = (
    "cgm_shipping.cgm_worldwide_shipping.customizations.website.get_cgm_website_user_home_page"
)

on_session_creation = [
    "cgm_shipping.cgm_worldwide_shipping.customizations.website.route_cgm_portal_after_login",
]

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# `local_datetime_iso` powers the timezone-aware <time> macros used across
# the customer portal templates.
jinja = {
    "methods": [
        "cgm_shipping.cgm_worldwide_shipping.customizations.portal_localize.local_datetime_iso",
 	    "cgm_shipping.cgm_worldwide_shipping.customizations.doc_qr.get_doc_qr_code",
   ],
}

# Installation
# ------------

# before_install = "cgm_shipping.install.before_install"
after_install = "cgm_shipping.install.after_install"
before_migrate = ["cgm_shipping.install.before_migrate"]
after_migrate = ["cgm_shipping.install.after_migrate"]

# Uninstallation
# ------------

# before_uninstall = "cgm_shipping.uninstall.before_uninstall"
# after_uninstall = "cgm_shipping.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "cgm_shipping.utils.before_app_install"
# after_app_install = "cgm_shipping.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "cgm_shipping.utils.before_app_uninstall"
# after_app_uninstall = "cgm_shipping.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "cgm_shipping.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
    "Task": ("cgm_shipping.cgm_worldwide_shipping.customizations.permissions"
            ".get_permission_query_conditions"),
}

has_permission = {
    "Task":
    ("cgm_shipping.cgm_worldwide_shipping.customizations.permissions.has_permission"
    ),
}

# Document class overrides
# ------------------------

override_doctype_class = {
    "Task":
    ["cgm_shipping.cgm_worldwide_shipping.customizations.task.CGMTask"],
    "Quotation":
    "cgm_shipping.cgm_worldwide_shipping.customizations.quotation.CGMQuotation",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Project": {
		"before_insert": "cgm_shipping.cgm_worldwide_shipping.customizations.project.assign_project_reference_on_insert",
		"after_insert": "cgm_shipping.cgm_worldwide_shipping.task_engine.on_project_after_insert",
		"onload": "cgm_shipping.cgm_worldwide_shipping.customizations.project.on_project_onload",
		"on_update": "cgm_shipping.cgm_worldwide_shipping.task_engine.on_project_update",
		"before_save": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.sync_consignee_from_customer",
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.sync_project_reference_on_save",
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.sync_project_ata_fields",
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.apply_shipment_document_automation",
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.sync_preshipment_containers_from_bl",
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.protect_finance_cost_ledger_from_manual_edit",
		],
	},
	"Purchase Invoice": {
		"validate": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.task.purchase_invoice_validate_from_task",
			"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.validate_share_with_transporter",
		],
		"on_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.task.purchase_invoice_on_submit",
	},
	"Payment Entry": {
		"validate": [
			"cgm_shipping.cgm_worldwide_shipping.overrides.payment_entry.validate_shipment_link",
			"cgm_shipping.cgm_worldwide_shipping.customizations.funding.copy_project_from_employee_advance",
		],
		"on_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.on_payment_entry_on_submit",
		"on_cancel": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.on_payment_entry_on_cancel",
	},
	"Sales Invoice": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.sales_invoice.validate_sales_invoice",
		"before_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.sales_invoice.before_submit_sales_invoice",
		"on_update": "cgm_shipping.cgm_worldwide_shipping.customizations.sales_invoice.on_update_sales_invoice_workflow",
	},
	"Journal Entry": {
		"after_insert": (
			"cgm_shipping.cgm_worldwide_shipping.customizations.finance_cost_ledger.sync_journal_entry_finance_cost"
		),
		"on_update": (
			"cgm_shipping.cgm_worldwide_shipping.customizations.finance_cost_ledger.sync_journal_entry_finance_cost"
		),
		"on_submit": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.task.journal_entry_on_submit",
			"cgm_shipping.cgm_worldwide_shipping.customizations.finance_cost_ledger.sync_journal_entry_finance_cost",
		],
		"on_cancel": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.task.journal_entry_on_cancel",
			"cgm_shipping.cgm_worldwide_shipping.customizations.finance_cost_ledger.sync_journal_entry_finance_cost",
		],
		"on_update_after_submit": (
			"cgm_shipping.cgm_worldwide_shipping.customizations.finance_cost_ledger.sync_journal_entry_finance_cost"
		),
	},
	"Customer": {
		"on_update": "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.on_customer_update",
	},
	"Supplier": {
		"on_update": "cgm_shipping.cgm_worldwide_shipping.customizations.transporter_supplier.sync_transporter_supplier_portal_users",
	},
	"Item": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.item_pricing.validate_item_pricing_rules",
	},
	"Leave Application": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.leave_application.validate_required_attachment",
	},
	"Material Request": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.on_material_request_validate",
		"on_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.on_material_request_on_submit",
	},
	"Purchase Order": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.on_purchase_document_validate",
	},
	"Request for Quotation": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.on_purchase_document_validate",
	},
	"Supplier Quotation": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.on_purchase_document_validate",
	},
	"Stock Entry": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.copy_project_to_stock_entry",
	},
	"Employee Advance": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.on_employee_advance_validate",
		"on_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.on_employee_advance_on_submit",
		"on_cancel": "cgm_shipping.cgm_worldwide_shipping.customizations.funding.on_employee_advance_on_cancel",
	},
	"Opportunity": {
		"onload": "cgm_shipping.cgm_worldwide_shipping.customizations.documents.on_opportunity_onload",
		"before_insert": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_intake_wizard.prepare_opportunity_intake",
			"cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment.assign_opportunity_batch_on_insert",
		],
		"validate": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_intake_wizard.validate_opportunity_intake",
		],
		"before_save": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_intake_wizard.sync_opportunity_intake_on_save",
			"cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment.sync_opportunity_batch_from_transport_doc",
			"cgm_shipping.cgm_worldwide_shipping.customizations.documents.normalize_opportunity_clients_documents",
			"cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment.seed_required_documents_on_opportunity",
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.sync_opportunity_bl_from_clients_documents",
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.sync_preshipment_containers_from_bl",
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.stamp_verified_documents_on_approval",
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.sync_linked_project_from_opportunity",
		],
		"before_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.stamp_verified_documents_on_approval",
		"before_update_after_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.stamp_verified_documents_on_approval",
		"on_trash": "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.clear_back_links_on_trash",
	},
	"Lead": {
		"before_save": (
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.sync_preshipment_containers_from_bl"
		),
	},
	"Task": {
		"onload": "cgm_shipping.cgm_worldwide_shipping.customizations.task.on_task_onload",
		"before_save": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.task.before_task_save",
			"cgm_shipping.cgm_worldwide_shipping.customizations.task.validate_task_completion_requirements",
		],
		"on_update": "cgm_shipping.cgm_worldwide_shipping.customizations.task.on_task_update",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    "daily": [
        "cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker.refresh_open_container_metrics",
        "cgm_shipping.cgm_worldwide_shipping.customizations.container_charges.post_all_container_charge_accruals",
    ],
}

# scheduler_events = {
# 	"all": [
# 		"cgm_shipping.tasks.all"
# 	],
# 	"daily": [
# 		"cgm_shipping.tasks.daily"
# 	],
# 	"hourly": [
# 		"cgm_shipping.tasks.hourly"
# 	],
# 	"weekly": [
# 		"cgm_shipping.tasks.weekly"
# 	],
# 	"monthly": [
# 		"cgm_shipping.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "cgm_shipping.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "cgm_shipping.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
    "erpnext.selling.doctype.quotation.quotation.make_sales_invoice":
    ("cgm_shipping.cgm_worldwide_shipping.customizations.quotation.make_sales_invoice"
     ),
    "erpnext.stock.doctype.material_request.material_request.make_purchase_order":
    "cgm_shipping.cgm_worldwide_shipping.customizations.funding.make_purchase_order",
    "erpnext.stock.doctype.material_request.material_request.make_request_for_quotation":
    "cgm_shipping.cgm_worldwide_shipping.customizations.funding.make_request_for_quotation",
    "erpnext.stock.doctype.material_request.material_request.make_supplier_quotation":
    "cgm_shipping.cgm_worldwide_shipping.customizations.funding.make_supplier_quotation",
    "erpnext.stock.doctype.material_request.material_request.make_purchase_order_based_on_supplier":
    "cgm_shipping.cgm_worldwide_shipping.customizations.funding.make_purchase_order_based_on_supplier",
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "cgm_shipping.task.get_dashboard_data"
# }
override_doctype_dashboards = {
    "Opportunity":
    "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.get_dashboard_data",
    "Project":
    "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_project_dashboard_data",
    "Material Request":
    "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_material_request_dashboard_data",
    "Employee Advance":
    "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_employee_advance_dashboard_data",
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["cgm_shipping.utils.before_request"]
before_request = [
	"cgm_shipping.cgm_worldwide_shipping.customizations.website.redirect_transporter_portal_users_from_desk",
]
# after_request = ["cgm_shipping.utils.after_request"]

# Job Events
# ----------
# before_job = ["cgm_shipping.utils.before_job"]
# after_job = ["cgm_shipping.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"cgm_shipping.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Fixtures loaded on migrate.
# CGM Task Template is intentionally NOT listed: company admins edit templates in
# the browser; seeding only creates missing defaults (see task_template_seed_data).
fixtures = [
	"Container Tracker Mode",
]

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
