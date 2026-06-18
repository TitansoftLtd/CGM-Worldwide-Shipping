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
app_include_css = "/assets/cgm_shipping/css/project_tracking.css"
app_include_js = "/assets/cgm_shipping/js/cgm_container_tracking.js"

# include js, css files in header of web template
# Customer portal: shared design-system CSS + browser-side timezone
# localization for the /portal, /my-shipments, /shipment and /documents pages.
web_include_css = [
	"/assets/cgm_shipping/css/customer_portal.css",
]
web_include_js = [
	"/assets/cgm_shipping/js/portal_localize_time.js",
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
	"Task": "public/js/task.js",
	"Purchase Invoice": "public/js/purchase_invoice.js",
	"Project": [
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
	"Opportunity": [
		"public/js/cgm_transport_reference.js",
		"public/js/cgm_bl_containers.js",
		"public/js/crm_opportunity.js",
	],
	"Quotation": "public/js/quotation.js",
	"Bill of Lading": "public/js/cgm_transport_reference.js",
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
# Customers (Website Users) land on the branded shipment portal.
role_home_page = {
	"Customer": "portal",
}

on_session_creation = [
	"cgm_shipping.cgm_worldwide_shipping.customizations.website.route_customer_to_portal",
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
	],
}

# Installation
# ------------

# before_install = "cgm_shipping.install.before_install"
# after_install = "cgm_shipping.install.after_install"
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
	"Task": (
		"cgm_shipping.cgm_worldwide_shipping.customizations.permissions"
		".get_permission_query_conditions"
	),
}

has_permission = {
	"Task": (
		"cgm_shipping.cgm_worldwide_shipping.customizations.permissions.has_permission"
	),
}

# Document class overrides
# ------------------------

override_doctype_class = {
	"Task": ["cgm_shipping.cgm_worldwide_shipping.customizations.task.CGMTask"],
	"Quotation": "cgm_shipping.cgm_worldwide_shipping.customizations.quotation.CGMQuotation",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Project": {
		"before_insert": "cgm_shipping.cgm_worldwide_shipping.customizations.project.assign_project_reference_on_insert",
		"before_save": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.sync_consignee_from_customer",
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.apply_shipment_document_automation",
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.sync_preshipment_containers_from_bl",
		],
	},
	"Purchase Invoice": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.customizations.task.purchase_invoice_validate_from_task",
		"on_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.task.purchase_invoice_on_submit",
	},
	"Payment Entry": {
		"validate": "cgm_shipping.cgm_worldwide_shipping.overrides.payment_entry.validate_shipment_link",
	},
	"Journal Entry": {
		"on_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.task.journal_entry_on_submit",
		"on_cancel": "cgm_shipping.cgm_worldwide_shipping.customizations.task.journal_entry_on_cancel",
	},
	"Customer": {
		"on_update": "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.on_customer_update",
	},
	"Opportunity": {
		"before_save": [
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.sync_opportunity_bl_from_clients_documents",
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.sync_preshipment_containers_from_bl",
		],
		"before_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.stamp_verified_documents_on_approval",
		"before_update_after_submit": "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.stamp_verified_documents_on_approval",
		"on_trash": "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.clear_back_links_on_trash",
	},
	"Lead": {
		"before_save": "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.sync_preshipment_containers_from_bl",
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
	"Opportunity": "cgm_shipping.cgm_worldwide_shipping.customizations.shipment.get_dashboard_data",
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
