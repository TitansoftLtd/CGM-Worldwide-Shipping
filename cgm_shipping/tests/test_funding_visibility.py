"""Who sees every Material Request, and who sees only their own.

Rules pinned here:

* The roles listed in Settings see every request. A Funding Approver saw 5 of 17
  because her own Employee user permission filtered the list.
* Everyone else sees what they saw before: requests naming them as requester,
  requests with no requester, and any they created.
* A user with no Employee user permission was never restricted and still is not.
* Only the requester field is exempt from user permissions. Company, Project and
  the rest still apply, and Funding Request is left exactly as Frappe has it.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import request_visibility as rv

MODULE = Path(frappe.get_app_path("cgm_shipping")) / "cgm_worldwide_shipping"


def _as(roles, employees):
	return (
		patch.object(frappe, "get_roles", return_value=list(roles)),
		patch.object(rv, "see_all_roles", return_value={"Finance User", "Funding Approver", "System Manager"}),
		patch.object(rv, "restricted_employees", return_value=list(employees)),
	)


def _doc(**fields):
	return frappe._dict(fields)


class TestSeeAll(unittest.TestCase):
	def _conditions(self, roles, employees, user="u@x"):
		a, b, c = _as(roles, employees)
		with a, b, c:
			return rv.material_request_query_conditions(user)

	def _may_open(self, roles, employees, doc, user="u@x"):
		a, b, c = _as(roles, employees)
		with a, b, c:
			return rv.material_request_has_permission(doc, "read", user)

	def test_listed_role_sees_every_request(self):
		self.assertEqual(self._conditions(["Employee", "Funding Approver"], ["EMP-1"]), "")
		self.assertTrue(self._may_open(["Funding Approver"], ["EMP-1"], _doc(custom_employee="EMP-9", owner="z@x")))

	def test_administrator_sees_every_request(self):
		self.assertEqual(self._conditions([], ["EMP-1"], user="Administrator"), "")

	def test_other_staff_are_limited_to_their_own(self):
		sql = self._conditions(["Employee"], ["EMP-1"])
		self.assertIn("`custom_employee` in ('EMP-1')", sql)
		self.assertIn("`owner` = 'u@x'", sql)
		self.assertIn("ifnull(`tabMaterial Request`.`custom_employee`, '') = ''", sql)

	def test_other_staff_open_only_their_own(self):
		roles, mine = ["Employee"], ["EMP-1"]
		self.assertTrue(self._may_open(roles, mine, _doc(custom_employee="EMP-1", owner="z@x")))
		self.assertTrue(self._may_open(roles, mine, _doc(custom_employee=None, owner="z@x")))
		self.assertTrue(self._may_open(roles, mine, _doc(custom_employee="EMP-9", owner="u@x")))
		self.assertFalse(self._may_open(roles, mine, _doc(custom_employee="EMP-9", owner="z@x")))

	def test_a_user_who_was_never_restricted_is_not_restricted_now(self):
		self.assertEqual(self._conditions(["Employee"], []), "")
		self.assertTrue(self._may_open(["Employee"], [], _doc(custom_employee="EMP-9", owner="z@x")))

	def test_an_empty_settings_table_means_the_defaults(self):
		settings = frappe._dict(meta=frappe._dict(has_field=lambda f: True))
		settings.get = lambda key: []
		with patch.object(frappe, "get_cached_doc", return_value=settings):
			roles = rv.see_all_roles()
		self.assertTrue(set(rv.DEFAULT_ROLES) <= roles)
		self.assertIn("System Manager", roles)


class TestOnlyTheRequesterFieldIsExempt(unittest.TestCase):
	def test_material_request(self):
		data = json.loads((MODULE / "custom" / "material_request.json").read_text())
		exempt = sorted(
			f["fieldname"] for f in data["custom_fields"] if f["fieldtype"] == "Link" and f.get("ignore_user_permissions")
		)
		self.assertEqual(exempt, ["custom_employee"])
		self.assertEqual([p for p in data["property_setters"] if p["property"] == "ignore_user_permissions"], [])

	def test_funding_request_is_left_alone(self):
		data = json.loads((MODULE / "doctype" / "funding_request" / "funding_request.json").read_text())
		self.assertEqual([f["fieldname"] for f in data["fields"] if f.get("ignore_user_permissions")], [])
