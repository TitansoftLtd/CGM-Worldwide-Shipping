"""Seed the workflow/role records that used to be installed via the ``fixtures``
hook.

The fixture hook re-imported these on every ``bench migrate``. Moving the seed
into a one-off patch keeps the data installable on fresh sites while letting
admins edit the workflows in the DB without each migrate overwriting them.

The workflow JSON exports still live under ``cgm_shipping/fixtures`` and are
imported here with the same overwrite semantics fixtures used
(``import_doc`` -> ``force=True``). States and action masters are imported before
the Workflow docs that reference them.
"""

import os

import frappe
from frappe.core.doctype.data_import.data_import import import_doc

# Imported in dependency order: states and actions exist before the workflows
# that link to them.
FIXTURE_FILES = (
	"workflow_state.json",
	"workflow_action_master.json",
	"workflow.json",
)

ROLES = (
	"Operations Manager",
	"Declarant",
	"Finance User",
	"Field Officer",
	"Transport Officer",
)


def execute():
	fixtures_path = frappe.get_app_path("cgm_shipping", "fixtures")
	for fname in FIXTURE_FILES:
		file_path = os.path.join(fixtures_path, fname)
		if os.path.exists(file_path):
			import_doc(file_path)

	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role,
					"desk_access": 1,
				}
			).insert(ignore_permissions=True)
