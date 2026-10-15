"""Nothing in this app may overwrite what production has done.

A deploy runs `bench migrate`, and several Frappe mechanisms re-import app files
on the way through. Each one is a way for somebody's deliberate change to vanish
with no error and no record:

* **Fixtures** are re-imported and *overwritten* every migrate. Frappe's own
  docstring says so. Container Tracker Mode shipped as one, and all five records
  on production carried the same `modified` timestamp to the millisecond - the
  moment of the last deploy.
* **DocType JSON** replaces the DocPerm rows, which is why permissions added by
  editing a DocType kept disappearing.

The fixture is gone and the modes are seeded create-if-missing instead. These
tests fail if either comes back.
"""

import unittest
from pathlib import Path

import frappe


class TestNoOverwritingFixtures(unittest.TestCase):
	def test_the_app_ships_no_fixtures_directory(self):
		"""`sync_fixtures` walks the directory, not the hooks list.

		Emptying `fixtures = []` in hooks.py changes nothing on its own - that list
		is only read when *exporting*. The file has to be absent, which is why this
		checks the directory rather than the hook.
		"""
		path = Path(frappe.get_app_path("cgm_shipping")) / "fixtures"
		leftover = sorted(p.name for p in path.glob("*.json")) if path.exists() else []
		self.assertEqual(
			leftover,
			[],
			"a fixture here is re-imported and overwritten on every deploy, "
			"silently reverting whatever production has done to those records",
		)

	def test_the_fixtures_hook_is_empty(self):
		hooks = frappe.get_hooks("fixtures", app_name="cgm_shipping") or []
		self.assertEqual(list(hooks), [])


class TestModesAreSeededNotOwned(unittest.TestCase):
	"""Seeding fills gaps; it must not restate what is already there."""

	MODE = "Container Tracker Mode"

	def setUp(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import container_tracker_modes as M

		self.seed = M.ensure_container_tracker_modes
		self.names = [m["mode_name"] for m in M.MODES]

	def tearDown(self):
		frappe.db.rollback()

	def test_a_business_edit_survives_seeding(self):
		name = self.names[0]
		if not frappe.db.exists(self.MODE, name):
			self.skipTest(f"{name} not on this site")
		frappe.db.set_value(self.MODE, name, "description", "EDITED BY THE BUSINESS")
		frappe.db.set_value(self.MODE, name, "is_active", 0)
		self.seed()
		self.assertEqual(frappe.db.get_value(self.MODE, name, "description"), "EDITED BY THE BUSINESS")
		self.assertEqual(frappe.db.get_value(self.MODE, name, "is_active"), 0)

	def test_a_missing_mode_is_created(self):
		name = self.names[-1]
		frappe.db.delete(self.MODE, {"name": name})
		self.seed()
		self.assertTrue(frappe.db.exists(self.MODE, name))

	def test_seeding_twice_changes_nothing(self):
		self.seed()
		before = frappe.db.count(self.MODE)
		self.seed()
		self.assertEqual(frappe.db.count(self.MODE), before)


class TestPermissionsSurviveDeploys(unittest.TestCase):
	"""A deploy may introduce access. It may never take any away.

	Every migrate replaces a DocType's `DocPerm` rows with the app's JSON, which
	is why permissions set by editing a DocType kept vanishing. Once a DocType has
	any `Custom DocPerm` row, Frappe uses those instead and a re-import cannot
	reach them, so the guard moves this app's DocTypes behind that hatch and then
	only ever adds.
	"""

	DT = "Warehouse Station"

	def setUp(self):
		from cgm_shipping.cgm_worldwide_shipping.customizations import permission_guard as PG

		self.guard = PG
		if not frappe.db.exists("DocType", self.DT):
			self.skipTest(f"{self.DT} is not on this site")

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache()

	def _rows(self):
		return {
			r.role: r
			for r in frappe.get_all(
				"Custom DocPerm",
				filters={"parent": self.DT},
				fields=["role", "read", "write", "report", "print"],
			)
		}

	def test_only_this_apps_doctypes_are_touched(self):
		"""ERPNext's and Frappe's permissions are not ours to freeze."""
		owned = set(self.guard._app_doctypes())
		for foreign in ("Sales Invoice", "User", "Opportunity Type", "Project"):
			self.assertNotIn(foreign, owned)

	def test_child_tables_are_skipped(self):
		"""They inherit their parent's permissions; freezing them means nothing."""
		owned = set(self.guard._app_doctypes())
		istables = set(
			frappe.get_all(
				"DocType", filters={"module": self.guard.MODULE, "istable": 1}, pluck="name"
			)
		)
		self.assertFalse(owned & istables)

	def test_a_narrowed_role_is_left_alone(self):
		"""Someone removed a flag on purpose. A deploy does not restore it."""
		row = frappe.db.get_value("Custom DocPerm", {"parent": self.DT, "role": "All"}, "name")
		if not row:
			self.skipTest("no 'All' row on this site")
		frappe.db.set_value("Custom DocPerm", row, "report", 0)
		self.guard.ensure_permissions_survive_deploy()
		self.assertEqual(self._rows()["All"].report, 0)

	def test_a_role_the_site_added_is_kept(self):
		extra = frappe.new_doc("Custom DocPerm")
		extra.update(
			{
				"parent": self.DT, "parenttype": "DocType", "parentfield": "permissions",
				"role": "Projects Manager", "permlevel": 0, "read": 1, "write": 1,
			}
		)
		extra.insert(ignore_permissions=True)
		self.guard.ensure_permissions_survive_deploy()
		self.assertIn("Projects Manager", self._rows())

	def test_running_it_twice_adds_nothing(self):
		self.guard.ensure_permissions_survive_deploy()
		before = frappe.db.count("Custom DocPerm", {"parent": self.DT})
		self.guard.ensure_permissions_survive_deploy()
		self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": self.DT}), before)


class TestNoPhantomRoles(unittest.TestCase):
	"""A permission naming a role that does not exist does nothing, quietly.

	Frappe skips such rows on import without warning, so the grant looks present
	in the file and is absent on the site. `CGM Documentation` sat in five DocType
	JSONs this way: the role exists nowhere, the real one is `Documentation`, and
	the grants had never worked.

	Nothing surfaces this - not a migrate, not a log - so it is checked here.
	"""

	import json as _json
	from pathlib import Path as _Path

	@classmethod
	def setUpClass(cls):
		cls.app = cls._Path(frappe.get_app_path("cgm_shipping"))

	def _doctype_files(self):
		return sorted((self.app / "cgm_worldwide_shipping" / "doctype").glob("*/*.json"))

	def test_every_role_granted_in_a_doctype_exists(self):
		phantom = {}
		for path in self._doctype_files():
			try:
				doc = self._json.loads(path.read_text())
			except Exception:
				continue
			if doc.get("doctype") != "DocType":
				continue
			for perm in doc.get("permissions") or []:
				role = perm.get("role")
				if role and not frappe.db.exists("Role", role):
					phantom.setdefault(doc["name"], []).append(role)

		self.assertEqual(
			phantom,
			{},
			"these DocTypes grant permissions to roles that do not exist, so the "
			f"grants silently do nothing: {phantom}",
		)

	def test_the_known_phantom_is_not_granted_anywhere(self):
		"""Named explicitly so a copy-paste cannot quietly bring it back.

		Checks the permission rows, not the file text: a role may legitimately be
		mentioned in a comment or a field description without being granted.
		"""
		offenders = []
		for path in self._doctype_files():
			try:
				doc = self._json.loads(path.read_text())
			except Exception:
				continue
			for perm in doc.get("permissions") or []:
				if perm.get("role") == "CGM Documentation":
					offenders.append(doc.get("name"))
		self.assertEqual(offenders, [])
