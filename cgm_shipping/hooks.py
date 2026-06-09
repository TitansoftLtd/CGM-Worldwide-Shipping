app_name = "cgm_shipping"
app_title = "CGM Worldwide Shipping"
app_publisher = "Titansoft Limited"
app_description = "CGM Customizations"
app_email = "nkubitudouglas@gmail.com"
app_license = "mit"

fixtures = [
    # Workflow definitions
    {
        "doctype": "Workflow",
        "filters": [["name", "in", [
            "CGM Lead Pre-Shipment",
            "CGM Opportunity Pre-Shipment",
            "CGM Sea Import Workflow",
        ]]]
    },
    # Workflow states
    {
        "doctype": "Workflow State",
        "filters": [["name", "in", [
            # Lead states
            "Lead Intake",
            "Lead Docs Verified",
            "Lead Docs Rejected",
            "Lead Ready to Convert",
            # Opportunity states
            "Opp Intake",
            "Opp Docs Verified",
            "Opp Docs Rejected",
            "Opp Ready for Project",
            # Project - sea freight clearance (custom_shipment_status)
            "Draft",
            "Documents Received",
            "UCR Applied",
            "UCR Paid",
            "Pre-clearance",
            "Client Inspection",
            "In Transit",
            "Final Docs Received",
            "Entry Lodged",
            "Manifest Requested",
            "Line Paid & DO Lodged",
            "Entry Paid",
            "Post-clearance",
            "Field Clearance",
            "KPA Paid",
            "In Delivery",
            "Containers Returned",
            "Completed",
            "Settled",
        ]]]
    },
    # Workflow actions
    {
        "doctype": "Workflow Action Master",
        "filters": [["name", "in", [
            # CRM actions
            "Approve CI/PKL",
            "Reject CI/PKL",
            "Approve customer onboarding",
            "Authorize Shipment File",
            # Project - sea freight clearance actions
            "Receive Client Documents",
            "Create UCR Application",
            "Confirm UCR Paid",
            "Start Pre-clearance Permits",
            "Request Client Inspection",
            "Start Shipment Tracking",
            "Receive Final Documents",
            "Request Manifest and Charges",
            "Lodge Customs Entry",
            "Confirm Line Paid and DO Lodged",
            "Confirm Entry Paid",
            "Complete Post-clearance Permits",
            "Hand to Field Officers",
            "Confirm KPA Paid",
            "Dispatch Cargo",
            "Confirm Containers Returned",
            "Complete Shipment File",
            "Settle File",
        ]]]
    },
    {
        "doctype": "Custom Field",
        "filters": [["module", "=", "CGM Worldwide Shipping"], ["name", "like", "custom_%"]],
    },
    {
        "doctype": "Role",
        "filters": [["name", "in", [
            "Operations Manager",
            "Declarant",
            "Finance User",
            "Field Officer",
            "Transport Officer",
        ]]],
    },
    {
        "doctype": "Notification",
        "filters": [["name", "like", "CGM%"]],
    },
]
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
app_include_css = "/assets/cgm_shipping/css/project_tracking.css"
app_include_js = "/assets/cgm_shipping/js/cgm_container_tracking.js"

# include js, css files in header of web template
# web_include_css = "/assets/cgm_shipping/css/cgm_shipping.css"
# web_include_js = "/assets/cgm_shipping/js/cgm_shipping.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "cgm_shipping/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}


# include js in doctype views
doctype_js = {
	"Task": "public/js/task.js",
	"Purchase Invoice": "public/js/purchase_invoice.js",
	"Payment Entry": "public/js/payment_entry.js",
	"Project": [
		"public/js/cgm_bl_containers.js",
		"public/js/project.js",
	],
	"Lead": [
		"public/js/cgm_bl_containers.js",
		"public/js/crm_lead.js",
	],
	"Customer": "public/js/crm_customer.js",
	"Opportunity": [
		"public/js/cgm_transport_reference.js",
		"public/js/cgm_bl_containers.js",
		"public/js/crm_opportunity.js",
	]
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
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
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "cgm_shipping.utils.jinja_methods",
# 	"filters": "cgm_shipping.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "cgm_shipping.install.before_install"
# after_install = "cgm_shipping.install.after_install"

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
	"Task": (
		"cgm_shipping.cgm_worldwide_shipping.customizations.task_permissions"
		".get_permission_query_conditions"
	),
}

has_permission = {
	"Task": (
		"cgm_shipping.cgm_worldwide_shipping.customizations.task_permissions.has_permission"
	),
}

# Document class overrides
# ------------------------

override_doctype_class = {
	"Task": ["cgm_shipping.cgm_worldwide_shipping.customizations.task_overrides.CGMTask"],
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Project": {
		"before_insert": "cgm_shipping.cgm_worldwide_shipping.customizations.project.assign_cgm_reference_on_insert",
		"before_save": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.sync_consignee_from_customer",
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.apply_shipment_document_automation",
			"cgm_shipping.cgm_worldwide_shipping.customizations.bl_containers.sync_preshipment_containers_from_bl",
		],
	},
	"Purchase Invoice": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.purchase_invoice_validate_from_task",
		"on_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.purchase_invoice_on_submit",
	},
	"Payment Entry": {
		"validate": [
			"cgm_shipping.cgm_worldwide_shipping.overrides.payment_entry.validate_shipment_link",
			"cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.payment_entry_validate_from_task",
		],
		"on_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.payment_entry_on_submit",
	},
	"Customer": {
		"on_update": "cgm_shipping.cgm_worldwide_shipping.customizations.customer.on_customer_update",
	},
	"Opportunity": {
		"before_save": (
			"cgm_shipping.cgm_worldwide_shipping.customizations.bl_containers"
			".sync_preshipment_containers_from_bl"
		),
	},
	"Lead": {
		"before_save": (
			"cgm_shipping.cgm_worldwide_shipping.customizations.bl_containers"
			".sync_preshipment_containers_from_bl"
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
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "cgm_shipping.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "cgm_shipping.task.get_dashboard_data"
# }
override_doctype_dashboards = {
	"Opportunity": "cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_dashboard.get_dashboard_data",
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

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
