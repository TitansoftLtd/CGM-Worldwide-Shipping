"""A notification goes to whoever is doing the work, not to everyone in the role.

A row naming a role reaches every holder. Field Operations Officers is twelve
people here, so one task produced a dozen messages, eleven of them noise - and
noise is how people learn to ignore the one that mattered.

Three rules, all exercised below:

* Somebody assigned -> only they get it.
* Nobody assigned -> fall back to the whole role, so nothing is silently dropped.
* A different role on the same notification is untouched, which is what makes it
  safe to put a narrowed role and a broad one side by side.

Routed per recipient row and resolved in one place for both channels, because
Frappe's own `send_to_all_assignees` is read on the email path only and half of
CGM's notifications are SMS.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import notification_routing as NR

ROUTES = {
	"Field Operations Officers": {"assigned_on": "Task", "fall_back_to_role": True},
	"Declarant": {"assigned_on": "Project", "fall_back_to_role": True},
	"Strict Role": {"assigned_on": "Task", "fall_back_to_role": False},
}


class TestResolution(unittest.TestCase):
	"""What a role row resolves to. None means "not routed, leave it alone"."""

	def _resolve(self, role, assigned):
		doc = frappe._dict(doctype="Task", name="TASK-1", project="PROJ-1")
		with patch.object(NR, "assigned_users", return_value=assigned):
			return NR.resolve_role_recipients(doc, role, ROUTES)

	def test_an_assignee_replaces_the_role(self):
		self.assertEqual(self._resolve("Field Operations Officers", ["a@x.com"]), ["a@x.com"])

	def test_several_assignees_all_get_it(self):
		self.assertEqual(
			self._resolve("Field Operations Officers", ["a@x.com", "b@x.com"]),
			["a@x.com", "b@x.com"],
		)

	def test_duplicates_are_collapsed(self):
		self.assertEqual(self._resolve("Field Operations Officers", ["a@x.com", "a@x.com"]), ["a@x.com"])

	def test_nobody_assigned_falls_back_to_the_role(self):
		"""None tells the caller to leave the row alone, so the role resolves as usual."""
		self.assertIsNone(self._resolve("Field Operations Officers", []))

	def test_a_role_that_is_not_routed_is_left_alone(self):
		"""This is what keeps a Director row on the same notification working."""
		self.assertIsNone(self._resolve("Director", ["a@x.com"]))

	def test_a_strict_rule_sends_to_nobody_rather_than_the_role(self):
		"""[] and None differ: [] is routed-but-empty, None is not routed."""
		self.assertEqual(self._resolve("Strict Role", []), [])

	def test_blank_assignees_are_dropped(self):
		self.assertIsNone(self._resolve("Field Operations Officers", [None, ""]))


class TestWhereItLooks(unittest.TestCase):
	"""Task rules read the task; Declarant rules read the shipment it belongs to."""

	def test_a_task_rule_reads_the_task(self):
		doc = frappe._dict(doctype="Task", name="TASK-1", project="PROJ-1")
		with patch.object(frappe, "get_all", return_value=["a@x.com"]) as get_all:
			NR.assigned_users(doc, "Task")
		filters = get_all.call_args.kwargs["filters"]
		self.assertEqual(filters["reference_type"], "Task")
		self.assertEqual(filters["reference_name"], "TASK-1")
		self.assertEqual(filters["status"], "Open")

	def test_a_project_rule_reads_the_linked_shipment(self):
		doc = frappe._dict(doctype="Task", name="TASK-1", project="PROJ-1")
		with patch.object(frappe, "get_all", return_value=["a@x.com"]) as get_all:
			NR.assigned_users(doc, "Project")
		filters = get_all.call_args.kwargs["filters"]
		self.assertEqual(filters["reference_type"], "Project")
		self.assertEqual(filters["reference_name"], "PROJ-1")

	def test_only_open_assignments_count(self):
		"""Completion closes assignments, which is what stops a finished job
		notifying the person who finished it."""
		doc = frappe._dict(doctype="Task", name="TASK-1")
		with patch.object(frappe, "get_all", return_value=[]) as get_all:
			NR.assigned_users(doc, "Task")
		self.assertEqual(get_all.call_args.kwargs["filters"]["status"], "Open")

	def test_a_task_with_no_shipment_resolves_to_nobody(self):
		doc = frappe._dict(doctype="Task", name="TASK-1")
		self.assertEqual(NR.assigned_users(doc, "Project"), [])

	def test_a_project_document_is_its_own_shipment(self):
		doc = frappe._dict(doctype="Project", name="PROJ-1")
		with patch.object(frappe, "get_all", return_value=[]) as get_all:
			NR.assigned_users(doc, "Project")
		self.assertEqual(get_all.call_args.kwargs["filters"]["reference_name"], "PROJ-1")


class TestAgainstTheRealNotification(unittest.TestCase):
	"""The override, the settings table and the roles, end to end."""

	FO = "Field Operations Officers"
	OTHER = "Director"

	@classmethod
	def setUpClass(cls):
		for role in (cls.FO, cls.OTHER):
			if not frappe.db.exists("Role", role):
				raise unittest.SkipTest(f"{role} is not on this site")
		if cls.FO not in NR.assignment_routes():
			raise unittest.SkipTest("assignment routing is not configured on this site")

	def tearDown(self):
		frappe.db.rollback()

	@staticmethod
	def _emails(role):
		users = {
			u
			for u in set(frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"))
			if frappe.db.get_value("User", u, "enabled")
		}
		return {frappe.db.get_value("User", u, "email") or u for u in users}

    # kept separate so the assertions below read as one comparison each
	def _fixture(self):
		task = frappe.new_doc("Task")
		task.subject = "Notification routing test"
		task.status = "Open"
		task.flags.ignore_validate = True
		task.insert(ignore_permissions=True, ignore_mandatory=True)

		alert = frappe.new_doc("Notification")
		alert.subject = "Routing test"
		alert.document_type = "Task"
		alert.event = "Value Change"
		alert.value_changed = "status"
		alert.channel = "Email"
		alert.message = "test"
		alert.append("recipients", {"receiver_by_role": self.FO})
		alert.append("recipients", {"receiver_by_role": self.OTHER})
		alert.flags.ignore_validate = True
		alert.insert(ignore_permissions=True, ignore_mandatory=True)
		return task, alert

	def test_the_override_is_in_use(self):
		task, alert = self._fixture()
		self.assertEqual(type(alert).__name__, "CGMNotification")

	def test_with_nobody_assigned_both_roles_are_reached(self):
		task, alert = self._fixture()
		got = set(alert.get_list_of_recipients(task, {"doc": task, "alert": alert})[0])
		self.assertEqual(got, self._emails(self.FO) | self._emails(self.OTHER))

	def test_an_assignee_replaces_their_role_but_not_the_other_one(self):
		from frappe.desk.form.assign_to import add as assign_add

		task, alert = self._fixture()
		fo_users = {
			u
			for u in set(frappe.get_all("Has Role", filters={"role": self.FO, "parenttype": "User"}, pluck="parent"))
			if frappe.db.get_value("User", u, "enabled")
		}
		other_users = set(
			frappe.get_all("Has Role", filters={"role": self.OTHER, "parenttype": "User"}, pluck="parent")
		)
		candidates = sorted(fo_users - other_users)
		if not candidates:
			self.skipTest("every holder of the routed role also holds the other one")
		assignee = candidates[0]
		assign_add(
			{"doctype": "Task", "name": task.name, "assign_to": [assignee], "description": "test"}
		)
		assignee_email = frappe.db.get_value("User", assignee, "email") or assignee

		got = set(alert.get_list_of_recipients(task, {"doc": task, "alert": alert})[0])
		self.assertEqual(got, {assignee_email} | self._emails(self.OTHER))
		spared = self._emails(self.FO) - self._emails(self.OTHER) - {assignee_email}
		self.assertFalse(spared & got, "other holders of the routed role were still messaged")
