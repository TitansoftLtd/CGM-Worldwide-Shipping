"""Seed the two roles that should notify the assignee rather than the whole role.

Why these two: a notification row naming a role reaches every holder of it. Field
Operations Officers is twelve people and Declarant is eight, so one task produced a
dozen messages, eleven of them noise - and noise is how people learn to ignore the
message that mattered.

* **Field Operations Officers** - routed on the **task**, because field work is
  owned per task.
* **Declarant** - routed on the **project**, because declaration work is owned per
  shipment; the declarant handling a shipment handles all of its tasks.

Both fall back to the whole role when nobody is assigned, so nothing is ever
silently dropped. Roles not listed here keep their existing behaviour, which is
what lets a Director row on the same notification still reach every Director.

Seeds only what is missing, so a site that has tuned these rows keeps its own.

Idempotent. Retire per docs/guides/patches.md once staging and production Patch Log
show it.
"""

import frappe

DOCTYPE = "CGM Shipping Settings"
FIELD = "notification_assignment_routes"

ROUTES = [
	{"role": "Field Operations Officers", "assigned_on": "Task", "fall_back_to_role": 1},
	{"role": "Declarant", "assigned_on": "Project", "fall_back_to_role": 1},
]


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		print(f"{DOCTYPE} is not installed; nothing to seed.")
		return
	if not frappe.get_meta(DOCTYPE).has_field(FIELD):
		print(f"{FIELD} is not on this site yet; nothing to seed.")
		return

	settings = frappe.get_single(DOCTYPE)
	existing = {row.role for row in settings.get(FIELD) or []}

	added = []
	for route in ROUTES:
		if route["role"] in existing:
			continue
		if not frappe.db.exists("Role", route["role"]):
			# A site without the role has nothing to route; seeding it would only
			# leave a row pointing at nothing.
			print(f"Role {route['role']!r} does not exist here; skipped.")
			continue
		settings.append(FIELD, route)
		added.append(route["role"])

	if not added:
		print("Every assignment route is already configured.")
		return

	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()
	print(f"Seeded assignment routing for: {', '.join(added)}")
