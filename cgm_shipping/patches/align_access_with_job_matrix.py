"""Align roles, Role Profiles, Module Profiles and the Desktop with CGM's access matrix.

Why: staff carried several stacked role profiles, and most profiles held the
"Documentation" role, so declarants, field officers and finance saw the admin and
operations task queues. Profiles also carried roles for ERPNext modules CGM does
not use, approvals belonging to other people (QA and the CFO could approve at the
Director, HR and Senior Supervisor steps), and delete rights the matrix rules out
("view and download, not delete"). Every user also saw Desktop icons such as
Financial Reports, Quality and ERPNext Settings, because those icons appear for
anyone who can read a common record like Company or Contact.

What, on this site's own records (the same edits the desk makes):

* Role Profiles: one per job, created or set to exactly ``ROLE_PROFILES``.
  Users holding them are re-saved so their roles follow.
* Module Profiles: created or set from ``MODULE_PROFILES``.
* Permissions, through Frappe's permission API:
  - Accounts User cancels and amends a submitted Journal Entry but cannot delete one;
  - Projects User can no longer delete a Project or Task (Projects Manager still can);
  - read-only grants so finance, tracking and the documentation coordinator can open
    the records their documents link to (``READ_GRANTS``);
  - the "quality assurance and projects coordinator" role loses its HR and payroll
    rights and gets work access to the CGM documents, never delete or submit;
  - the wiki becomes read-only for everyone but Administrator. The docs sync runs as
    Administrator on migrate, so publishing ``docs/`` is unaffected.
* Settings > Roles: HR User leaves the Documentation task group, Senior Supervisor
  joins the Operations one (the field supervisor obtains the KPA invoice).
* Desktop Icon > Roles from ``DESKTOP_ICON_ROLES``.
* Roles CGM does not use are disabled, unless an enabled user still holds one.

Which person holds which profile is not here: that is site data, imported with
Data Import (User, "Update Existing Records") after this has run.

Idempotent: every step sets a target state and skips what already matches. One-time -
retire per docs/guides/patches.md once staging and production Patch Log show it.
Afterwards all of this is maintained in the desk. A newer ERPNext or HRMS Desktop
Icon file resets that icon's roles when it is re-imported; set them again there.
"""

import frappe

# One profile per job; every role a holder needs, nothing stacked on top.
ROLE_PROFILES: dict[str, tuple[str, ...]] = {
	"Accounts": (
		"Accounts User", "Employee", "Employee Self Service", "Finance User", "Projects User",
	),
	"Assistant Finance Manager": (
		"Accounts Manager", "Accounts User", "Employee", "Employee Self Service", "Expense Approver",
		"Finance Manager", "Finance User", "Funding Approver", "Leave Approver", "Projects User",
		"Purchase Manager", "Purchase User", "Stock User",
	),
	"Chairman": (
		"Accounts Manager", "Accounts User", "Analytics", "Auditor", "Dashboard Manager",
		"Documentation", "Employee", "Employee Self Service", "Expense Approver", "Item Manager",
		"Leave Approver", "Operations Manager", "Prepared Report User", "Projects Manager",
		"Projects User", "Purchase Manager", "Purchase Master Manager", "Purchase User",
		"Report Manager", "Sales Manager", "Sales Master Manager", "Sales User", "Stock Manager",
		"Stock User", "System Manager", "Transport Officer",
	),
	"Chief Financial Officer (CFO)": (
		"Accounts Manager", "Accounts User", "Analytics", "Auditor", "Dashboard Manager", "Employee",
		"Employee Self Service", "Expense Approver", "Finance Manager", "Finance User",
		"Funding Approver", "Leave Approver", "Prepared Report User", "Projects User",
		"Purchase Manager", "Purchase User", "Report Manager", "Stock User",
	),
	"Declarant": (
		"Declarant", "Employee", "Employee Self Service", "Projects User",
	),
	"Director": (
		"Accounts Manager", "Accounts User", "Analytics", "Auditor", "Dashboard Manager",
		"Declarant", "Director", "Documentation", "Employee", "Employee Self Service",
		"Expense Approver", "Field Operations Officers", "Finance Alerts", "Finance Manager",
		"Finance User", "Leave Approver", "License User", "Operations Manager",
		"Prepared Report User", "Projects Manager", "Projects User", "Purchase Manager",
		"Purchase User", "Report Manager", "Stock User", "Transport Officer",
	),
	"Documentation Coordinator": (
		"Dashboard Manager", "Declarant", "Documentation", "Documentation Coordinator", "Employee",
		"Employee Self Service", "Field Operations Officers", "Finance Manager", "Finance User",
		"Office Administration Executive", "Operations Admin Executive", "Operations Manager",
		"Opportunity Approver", "Projects Manager", "Projects User", "Senior Supervisor",
		"Tracking Officer", "Transport Officer",
	),
	"Field Operations Officer": (
		"Employee", "Employee Self Service", "Field Operations Officers", "Projects User",
		"Transport Officer",
	),
	"Field Supervisor & Logistics Manager": (
		"Employee", "Employee Self Service", "Expense Approver", "Field Operations Officers",
		"Leave Approver", "Projects Manager", "Projects User", "Senior Supervisor",
		"Tracking Officer", "Transport Officer",
	),
	"Finance User": (
		"Accounts User", "Employee", "Employee Self Service", "Expense Approver", "Finance User",
		"Projects User", "Purchase User", "Stock User",
	),
	"HR": (
		"CGM HR", "Employee", "Employee Self Service", "Expense Approver", "HR Manager", "HR User",
		"Leave Approver",
	),
	"Head of operations": (
		"Dashboard Manager", "Employee", "Employee Self Service", "Operations Manager",
		"Projects Manager", "Projects User", "Transport Officer",
	),
	"ICT Executive": (
		"Documentation", "Employee", "Employee Self Service", "ICT user", "Projects User",
	),
	"IT Support": (
		"Documentation", "Employee", "Employee Self Service", "ICT user", "Projects User",
		"System Manager",
	),
	"Leave Approver": (
		"Leave Approver",
	),
	"Marketing Manager": (
		"Marketing Manager",
	),
	"Operations Administration Executive": (
		"Dashboard Manager", "Documentation", "Employee", "Employee Self Service", "Item Manager",
		"License Manager", "Office Administration Executive", "Operations Admin Executive",
		"Projects User", "Stock User",
	),
	"Operations Manager": (
		"Dashboard Manager", "Employee", "Employee Self Service", "Leave Approver",
		"Operations Manager", "Opportunity Approver", "Projects Manager", "Projects User",
		"Sales User", "Senior Operations Manager",
	),
	"Operations Officer - Tracking & Transport": (
		"Dashboard Manager", "Employee", "Employee Self Service", "Projects User",
		"Tracking Officer", "Transport Officer",
	),
	"Operations Supervisor": (
		"Employee", "Employee Self Service", "Field Operations Officers", "Leave Approver",
		"Projects User", "Transport Officer",
	),
	"Quality Assurance and Projects coordinator": (
		"Analytics", "Auditor", "Dashboard Manager", "Declarant", "Documentation", "Employee",
		"Employee Self Service", "Field Operations Officers", "Finance User", "Item Manager",
		"License Manager", "License User", "Operations Manager", "Opportunity Approver",
		"Prepared Report User", "Projects Manager", "Projects User", "Purchase Manager",
		"Purchase Master Manager", "Purchase User", "Report Manager", "Sales Manager",
		"Sales Master Manager", "Sales User", "Stock Manager", "Stock User", "System Manager",
		"Tracking Officer", "Transport Officer", "quality assurance and projects coordinator",
	),
	"Staff Self Service": (
		"Employee", "Employee Self Service",
	),
}

# Modules each profile shows; every other module on the site is blocked.
MODULE_PROFILES: dict[str, tuple[str, ...]] = {
	"Self Service": (
		"Desk", "Expenses", "Frappe Wiki", "HR", "Leaves", "Payroll", "Performance",
		"Shift and Attendance", "Wiki",
	),
	"Operations": (
		"CGM Worldwide Shipping", "CRM", "Contacts", "Desk", "Expenses", "Frappe Wiki", "HR",
		"Leaves", "Payroll", "Performance", "Projects", "Shift and Attendance", "Wiki",
	),
	"Operations Management & Admin": (
		"Buying", "CGM Worldwide Shipping", "CRM", "Contacts", "Desk", "Expenses", "Frappe Wiki",
		"HR", "Leaves", "Payroll", "Performance", "Projects", "Selling", "Shift and Attendance",
		"Stock", "Wiki",
	),
	"Finance": (
		"Accounts", "Buying", "CGM Worldwide Shipping", "CRM", "Contacts", "Desk", "Expenses",
		"Frappe Wiki", "HR", "Leaves", "Payroll", "Performance", "Projects", "Regional", "Selling",
		"Setup", "Shift and Attendance", "Stock", "Tax and Benefits", "Wiki",
	),
	"Human Resources": (
		"Desk", "Expenses", "Frappe Wiki", "HR", "HR Setup", "Leaves", "Payroll", "Performance",
		"Recruitment", "Setup", "Shift and Attendance", "Tax and Benefits", "Tenure", "Wiki",
	),
	"Management": (
		"Accounts", "Buying", "CGM Worldwide Shipping", "CRM", "Contacts", "Desk", "Expenses",
		"Frappe Wiki", "HR", "HR Setup", "Leaves", "Payroll", "Performance", "Projects",
		"Recruitment", "Regional", "Selling", "Setup", "Shift and Attendance", "Stock",
		"Tax and Benefits", "Tenure", "Users", "Wiki",
	),
	"System Administration": (
		"Accounts", "Automation", "Build", "Buying", "CGM Worldwide Shipping", "CRM",
		"Communication", "Contacts", "Core", "Custom", "Data", "Desk", "Email", "Expenses",
		"Frappe Wiki", "Geo", "HR", "HR Setup", "Integrations", "Leaves", "Payroll", "Performance",
		"Portal", "Printing", "Projects", "Recruitment", "Regional", "Selling", "Setup",
		"Shift and Attendance", "Stock", "System", "Tax and Benefits", "Tenure", "Users",
		"Utilities", "Website", "Wiki", "Workflow",
	),
}

# (doctype, role, flags) on the permlevel-0 rule.
PERMISSION_CHANGES = (
	("Journal Entry", "Accounts User", {"delete": 0, "cancel": 1, "amend": 1}),
	("Project", "Projects User", {"delete": 0}),
	("Task", "Projects User", {"delete": 0}),
)

# Open and pick the linked record; never edit it.
READ_GRANTS = (
	("Container Tracker", "Finance User"),  # Task container rows on tasks finance works
	("Booking Confirmation", "Finance User"),  # Project > Booking Confirmation
	("Booking Confirmation", "Tracking Officer"),
	("Supplier", "Documentation Coordinator"),  # shipping line / transporter fields
	("Currency", "Documentation Coordinator"),  # Bill of Lading > Deposit Currency
)

QA_ROLE = "quality assurance and projects coordinator"
QA_FLAGS = {
	"read": 1, "write": 1, "create": 1, "report": 1, "export": 1, "print": 1, "email": 1, "share": 1,
	"delete": 0, "submit": 0, "cancel": 0, "amend": 0,
}
QA_MODULE = "CGM Worldwide Shipping"
QA_EXTRA_DOCTYPES = ("Project", "Task", "Opportunity", "Customer", "Supplier", "Material Request", "Item")

WIKI_DOCTYPES = (
	"Wiki Document", "Wiki Space", "Wiki Change Request", "Wiki Revision", "Wiki Revision Item",
	"Wiki Content Blob", "Wiki Merge Conflict", "Wiki Page", "Wiki Page Patch", "Wiki Page Revision",
	"Wiki Settings",
)
WIKI_EDITING_ROLES = ("System Manager", "All", "Wiki Manager", "Wiki Approver", "Wiki User")
EDIT_FLAGS = ("write", "create", "delete", "submit", "cancel", "amend")

# (Settings table, role, present?) - saving Settings carries these to CGM Role Group.
ROLE_GROUP_CHANGES = (
	("custom_documentation_roles", "HR User", False),
	("custom_operations_roles", "Senior Supervisor", True),
)

_SYS = ("System Manager",)
_FINANCE = ("Accounts User", "Accounts Manager", "Finance Manager", "Auditor", *_SYS)
_SHIPMENT = ("Projects User", "Projects Manager", *_SYS)
_CUSTOMERS_SUPPLIERS = (
	*_FINANCE, "Documentation", "Sales User", "Sales Manager", "Purchase User", "Purchase Manager",
	"Operations Manager",
)
_SELLING = ("Sales User", "Sales Manager", "Accounts User", "Accounts Manager", "Documentation", *_SYS)
_STOCK = ("Stock User", "Stock Manager", "Item Manager", *_SYS)
_HR = ("HR Manager", "HR User", *_SYS)
_EVERYONE = ()  # no roles: every desk user

DESKTOP_ICON_ROLES: dict[str, tuple[str, ...]] = {
	"CGM Shipping": _SHIPMENT,
	"Projects": _SHIPMENT,
	"Accounting": _CUSTOMERS_SUPPLIERS,
	"Invoicing": _CUSTOMERS_SUPPLIERS,
	"Financial Reports": _FINANCE,
	"Accounts Setup": _FINANCE,
	"Banking": _FINANCE,
	"Budget": _FINANCE,
	"Payments": _FINANCE,
	"Taxes": _FINANCE,
	"Share Management": _FINANCE,
	"Subscription": _FINANCE,
	"Selling": _SELLING,
	"Stock": _STOCK,
	"Buying": _EVERYONE,  # everyone raises Material Requests
	"HR Setup": _HR,
	"Recruitment": _HR,
	"Tenure": _HR,
	"Tax & Benefits": _HR,
	"Organization": ("HR Manager", *_SYS),
	"Leaves": _EVERYONE,
	"Expenses": _EVERYONE,
	"Payroll": _EVERYONE,
	"Shift & Attendance": _EVERYONE,
	"Performance": _EVERYONE,
	"Wiki": _EVERYONE,
	"ERPNext Settings": _SYS,
	"Quality": _SYS,
	"Manufacturing": _SYS,
	"Subcontracting": _SYS,
	"Assets": _SYS,
	"Automation": _SYS,
	"Build": _SYS,
	"Email": _SYS,
	"Integrations": _SYS,
	"System": _SYS,
	"Users": _SYS,
	"Website": _SYS,
	"Data": ("Accounts User", *_SYS),
}

UNUSED_ROLES = (
	"Academics User", "chairman", "Delivery Manager", "Delivery User", "Fleet Manager",
	"Fulfillment User", "Inbox User", "Interviewer", "Knowledge Base Contributor",
	"Knowledge Base Editor", "Maintenance Manager", "Maintenance User", "Manufacturing Manager",
	"Manufacturing User", "Newsletter Manager", "Quality Manager", "Support Team", "Translator",
	"Website Manager", "Wiki Approver", "Wiki Manager",
)


def execute():
	log: list[str] = []
	set_permissions(log)
	set_qa_role(log)
	lock_wiki(log)
	set_role_groups(log)
	set_role_profiles(log)
	set_module_profiles(log)
	set_desktop_icons(log)
	disable_unused_roles(log)
	frappe.clear_cache()
	print("\n".join(log) or "Access already matches the matrix.")


def _set_rule(doctype: str, role: str, flags: dict) -> list[str]:
	"""Set flags on the permlevel-0 rule, creating it if missing. Returns flags changed.

	`add_permission` copies the shipped rows into Custom DocPerm first, so a lone
	custom row never replaces a DocType's whole permission set.
	"""
	from frappe.permissions import add_permission, setup_custom_perms, update_permission_property

	setup_custom_perms(doctype)
	key = {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
	if not frappe.db.exists("Custom DocPerm", key):
		if not any(flags.values()):
			return []
		add_permission(doctype, role, 0)
	current = frappe.db.get_value("Custom DocPerm", key, list(flags), as_dict=True)
	changed = [flag for flag, value in flags.items() if (current.get(flag) or 0) != value]
	for flag in changed:
		update_permission_property(doctype, role, 0, flag, flags[flag])
	return changed


def set_permissions(log):
	for doctype, role, flags in PERMISSION_CHANGES:
		if frappe.db.exists("DocType", doctype) and _set_rule(doctype, role, flags):
			log.append(f"{doctype} / {role}: {flags}")
	for doctype, role in READ_GRANTS:
		if not (frappe.db.exists("DocType", doctype) and frappe.db.exists("Role", role)):
			continue
		if _set_rule(doctype, role, {"read": 1, "select": 1}):
			log.append(f"{doctype} / {role}: read")


def set_qa_role(log):
	if not frappe.db.exists("Role", QA_ROLE):
		return
	targets = set(
		frappe.get_all("DocType", filters={"module": QA_MODULE, "istable": 0, "issingle": 0}, pluck="name")
	) | {dt for dt in QA_EXTRA_DOCTYPES if frappe.db.exists("DocType", dt)}

	removed = []
	for name, doctype in frappe.get_all(
		"Custom DocPerm", filters={"role": QA_ROLE}, fields=["name", "parent"], as_list=True
	):
		if doctype not in targets:
			frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True, force=True)
			removed.append(doctype)
	granted = [dt for dt in sorted(targets) if _set_rule(dt, QA_ROLE, QA_FLAGS)]
	if removed:
		log.append(f"{QA_ROLE}: removed from {', '.join(sorted(set(removed)))}")
	if granted:
		log.append(f"{QA_ROLE}: works on {len(granted)} CGM document types")


def lock_wiki(log):
	from frappe.permissions import setup_custom_perms

	for doctype in WIKI_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		setup_custom_perms(doctype)
		for row in frappe.get_all(
			"Custom DocPerm",
			filters={"parent": doctype, "role": ("in", WIKI_EDITING_ROLES)},
			fields=["name", "role", *EDIT_FLAGS],
		):
			if any(row.get(flag) for flag in EDIT_FLAGS):
				frappe.db.set_value("Custom DocPerm", row.name, dict.fromkeys(EDIT_FLAGS, 0))
				log.append(f"{doctype} / {row.role}: read only")
		frappe.clear_cache(doctype=doctype)


def set_role_groups(log):
	settings = frappe.get_single("CGM Shipping Settings")
	changed = False
	for field, role, present in ROLE_GROUP_CHANGES:
		if not settings.meta.has_field(field):
			continue
		has = any(row.role == role for row in settings.get(field))
		if present and not has:
			settings.append(field, {"role": role})
		elif not present and has:
			settings.set(field, [row for row in settings.get(field) if row.role != role])
		else:
			continue
		changed = True
		log.append(f"Settings > {field}: {'added' if present else 'removed'} {role}")
	if changed:
		settings.flags.ignore_permissions = True
		settings.save()


def _resave_users_of(profile: str):
	for user in frappe.get_all("User Role Profile", filters={"role_profile": profile}, pluck="parent"):
		doc = frappe.get_doc("User", user)
		# v16 re-appends the deprecated single field on save; keep it on a held profile.
		if doc.role_profile_name and doc.role_profile_name not in [r.role_profile for r in doc.role_profiles]:
			doc.role_profile_name = None
		doc.flags.ignore_permissions = True
		doc.save()


def set_role_profiles(log):
	existing_roles = set(frappe.get_all("Role", pluck="name"))
	for name, roles in ROLE_PROFILES.items():
		missing = [r for r in roles if r not in existing_roles]
		if missing:
			log.append(f"Role Profile {name}: roles not on this site, skipped: {', '.join(missing)}")
		wanted = {r for r in roles if r in existing_roles}
		if frappe.db.exists("Role Profile", name):
			doc = frappe.get_doc("Role Profile", name)
			if {r.role for r in doc.roles} == wanted:
				continue
			action = "updated"
		else:
			doc = frappe.new_doc("Role Profile")
			doc.role_profile = name
			action = "created"
		doc.set("roles", [{"role": r} for r in sorted(wanted)])
		doc.save(ignore_permissions=True)
		# on_update queues a re-save of its users and locks the profile until it runs;
		# the users are re-saved here instead, so the lock is not needed.
		doc.unlock()
		_resave_users_of(name)
		log.append(f"Role Profile {name}: {action}")


def set_module_profiles(log):
	site_modules = set(frappe.get_all("Module Def", pluck="name"))
	for name, allowed in MODULE_PROFILES.items():
		blocked = sorted(site_modules - set(allowed))
		if frappe.db.exists("Module Profile", name):
			doc = frappe.get_doc("Module Profile", name)
			if {b.module for b in doc.block_modules} == set(blocked):
				continue
			action = "updated"
		else:
			doc = frappe.new_doc("Module Profile")
			doc.module_profile_name = name
			action = "created"
		doc.set("block_modules", [{"module": m} for m in blocked])
		doc.save(ignore_permissions=True)
		doc.unlock()
		log.append(f"Module Profile {name}: {action}")


def set_desktop_icons(log):
	existing_roles = set(frappe.get_all("Role", pluck="name"))
	# In developer mode saving a standard icon writes it back into its app's folder.
	in_import = frappe.flags.in_import
	frappe.flags.in_import = True
	try:
		for label, roles in DESKTOP_ICON_ROLES.items():
			name = frappe.db.get_value("Desktop Icon", {"label": label, "standard": 1})
			if not name:
				continue
			wanted = sorted(r for r in roles if r in existing_roles)
			doc = frappe.get_doc("Desktop Icon", name)
			if sorted(r.role for r in doc.roles) == wanted:
				continue
			doc.set("roles", [{"role": r} for r in wanted])
			doc.save(ignore_permissions=True)
			log.append(f"Desktop Icon {label}: {', '.join(wanted) or 'everyone'}")
	finally:
		frappe.flags.in_import = in_import
	frappe.cache.delete_key("desktop_icons")
	frappe.cache.delete_key("bootinfo")


def disable_unused_roles(log):
	for role in UNUSED_ROLES:
		if not frappe.db.exists("Role", role) or frappe.db.get_value("Role", role, "disabled"):
			continue
		holders = [
			user
			for user in frappe.get_all(
				"Has Role",
				filters={"role": role, "parenttype": "User", "parent": ("!=", "Administrator")},
				pluck="parent",
			)
			if frappe.db.get_value("User", user, "enabled")
		]
		if holders:
			log.append(f"Role {role}: still held by {', '.join(holders)}, left enabled")
			continue
		doc = frappe.get_doc("Role", role)
		doc.disabled = 1
		doc.save(ignore_permissions=True)
		log.append(f"Role {role}: disabled")
