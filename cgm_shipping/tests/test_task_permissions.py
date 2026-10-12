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

	def test_every_role_group_can_work_on_tasks(self):
		"""Each department the workflow routes Task work to needs one role with write.

		Department scoping is enforced separately by permission_query_conditions /
		has_permission, so granting write here does not widen what a user can see.
		"""
		writable = {p["role"] for p in self.perms if p["write"]}
		locked_out = {}
		for group, (_stems, roles) in DEFAULT_ROLE_GROUPS.items():
			existing = [r for r in roles if frappe.db.exists("Role", r)]
			if not existing:
				continue  # none of this group's roles are provisioned on this site
			if not (set(existing) & writable):
				locked_out[group] = existing
		self.assertEqual(
			locked_out,
			{},
			"Role groups with no write access to Task: "
			+ "; ".join(f"{g} (roles present: {r})" for g, r in locked_out.items()),
		)
