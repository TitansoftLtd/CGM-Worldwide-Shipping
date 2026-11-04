"""Guard the Task permission matrix.

Task carries Custom DocPerm rows, owned by Role Permission Manager on each site
(custom/task.json ships an empty custom_perms, so migrate leaves them alone). Frappe
ignores the standard DocPerms entirely once those exist, so they are the whole
access matrix for Task.

These are structural invariants, not site policy: they hold on any site the app
is installed on, and they fail loudly where the matrix has drifted from the role
groups the workflow actually routes work to.
"""

import unittest

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.document_responsibilities import (
	DEFAULT_ROLE_GROUPS,
)

TASK = "Task"


def _task_perms() -> list[dict]:
	return frappe.get_all(
		"Custom DocPerm",
		filters={"parent": TASK, "permlevel": 0},
		fields=["role", "`read`", "`write`", "`create`", "`delete`"],
	)


class TestTaskPermissionMatrix(unittest.TestCase):
	def setUp(self):
		self.perms = _task_perms()
		if not self.perms:
			self.skipTest("No Custom DocPerm rows for Task; standard DocPerms apply.")

	def test_create_implies_write(self):
		"""Creating a Task you cannot then edit is never intended."""
		broken = sorted(p["role"] for p in self.perms if p["create"] and not p["write"])
		self.assertEqual(
			broken,
			[],
			f"Roles can create a Task but not edit it: {broken}.",
		)

	def test_nobody_is_routed_work_they_cannot_do(self):
		"""Every user in a department the workflow routes Task work to can edit a Task.

		This used to require the department's OWN role to carry write, and failed
		permanently on a site where it does not: at CGM the field, transport and
		documentation people hold Projects User as well, so they can already edit
		every task they are allowed to see. Nobody was locked out, yet the matrix
		read as broken, and the suggested cure was to widen Task permissions for
		roles no user would have gained anything from.

		What matters is the person, not which of their roles carries the flag.
		Department scoping is enforced separately by permission_query_conditions /
		has_permission, so write here never widens what anyone can see.
		"""
		writable = {p["role"] for p in self.perms if p["write"]}
		locked_out = {}
		for group, (_stems, roles) in DEFAULT_ROLE_GROUPS.items():
			existing = [r for r in roles if frappe.db.exists("Role", r)]
			if not existing:
				continue  # none of this group's roles are provisioned on this site
			users = set()
			for role in existing:
				users |= {
					r.parent
					for r in frappe.get_all("Has Role", filters={"role": role}, fields=["parent"])
				}
			users = {u for u in users if frappe.db.get_value("User", u, "enabled")}
			if not users:
				continue  # nobody holds these roles here
			stuck = sorted(u for u in users if not (set(frappe.get_roles(u)) & writable))
			if stuck:
				locked_out[group] = stuck
		self.assertEqual(
			locked_out,
			{},
			"Users routed Task work they cannot edit: "
			+ "; ".join(f"{g} ({len(u)}: {u[:3]})" for g, u in locked_out.items()),
		)
