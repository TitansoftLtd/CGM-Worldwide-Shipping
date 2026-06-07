"""One-time seeding of CGM Shipping Settings defaults.

These values are the *initial* contents copied into CGM Shipping Settings — the
runtime source of truth is the Settings doc, not this module. Used by:
  * the after_install hook (fresh sites — patches don't run on install), and
  * patches v2_40 / v2_41 (existing sites, on migrate).
Seeding is idempotent: a field is only populated when it is currently empty.
"""

import frappe

# Initial role membership per group (only roles that exist on the site are seeded).
ROLE_SEED = {
	"custom_finance_roles": (
		"Finance Manager",
		"Finance User",
		"Accounts User",
		"Accounts Manager",
	),
	"custom_operations_roles": (
		"Operations Manager",
		"Operations User",
		"Declaration User",
		"Declarant",
		"System Manager",
	),
	"custom_declaration_roles": ("Declaration User", "Declarant", "System Manager"),
}


def seed_role_settings() -> bool:
	"""Populate empty role tables in CGM Shipping Settings. Returns True if changed."""
	settings = frappe.get_single("CGM Shipping Settings")
	changed = False
	for fieldname, roles in ROLE_SEED.items():
		if not settings.meta.has_field(fieldname) or settings.get(fieldname):
			continue
		for role in roles:
			if frappe.db.exists("Role", role):
				settings.append(fieldname, {"role": role})
				changed = True
	if changed:
		settings.save(ignore_permissions=True)
	return changed


def seed_email_template_settings() -> bool:
	"""Populate empty notification-template fields with the built-in defaults."""
	from cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow import (
		PERMIT_FINANCE_EMAIL_TEMPLATE,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_email_notifications import (
		DEFAULT_EMAIL_TEMPLATE,
	)
	from cgm_shipping.cgm_worldwide_shipping.customizations.ucr_payment_workflow import (
		UCR_FINANCE_EMAIL_TEMPLATE,
	)

	seed = {
		"custom_default_email_template": DEFAULT_EMAIL_TEMPLATE,
		"custom_permit_finance_email_template": PERMIT_FINANCE_EMAIL_TEMPLATE,
		"custom_ucr_finance_email_template": UCR_FINANCE_EMAIL_TEMPLATE,
	}
	settings = frappe.get_single("CGM Shipping Settings")
	changed = False
	for fieldname, template in seed.items():
		if settings.meta.has_field(fieldname) and not (settings.get(fieldname) or "").strip():
			settings.set(fieldname, template)
			changed = True
	if changed:
		settings.save(ignore_permissions=True)
	return changed


def after_install():
	"""Seed Settings defaults on a fresh install (patches don't run on install)."""
	seed_role_settings()
	seed_email_template_settings()
