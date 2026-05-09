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
            "CGM Sea Import Workflow",        # ← added
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
            # Sea Import states
            "Documents Received",             # ← added
            "IDF Created",                    # ← added
            "Permits Processing",             # ← added
            "Awaiting Arrival",               # ← added
            "Arrived",                        # ← added
            "Clearing",                       # ← added
            "Released",                       # ← added
            "In Transit",                     # ← added
            "Delivered",                      # ← added
            "Container Return Pending",       # ← added
            "Completed",                      # ← added
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
            # Sea Import actions
            "Approve Docs & Create IDF",      # ← added
            "Start Permits",                  # ← added
            "Permits Ready",                  # ← added
            "Mark Arrived",                   # ← added
            "Start Clearing",                 # ← added
            "Release Cargo",                  # ← added
            "Dispatch Truck",                 # ← added
            "Confirm Delivery",               # ← added
            "Start Container Return",         # ← added
            "Confirm Interchange & Close",    # ← added
        ]]]
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
# app_include_css = "/assets/cgm_shipping/css/cgm_shipping.css"
# app_include_js = "/assets/cgm_shipping/js/cgm_shipping.js"

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
	"Project": "public/js/project.js",
	"Lead": "public/js/crm_lead.js",
	"Customer": "public/js/crm_customer.js",
	"Opportunity": "public/js/crm_opportunity.js",
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

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Project": {
		"before_save": "cgm_shipping.cgm_worldwide_shipping.customizations.project.apply_shipment_document_automation",
	},
}

# Scheduled Tasks
# ---------------

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

