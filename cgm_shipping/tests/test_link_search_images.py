"""Link pickers stop crashing for users who may only select a record.

Frappe 16.60's `add_images` builds `dict(get_list(..., fields=["name", image_field]))`.
For a select-only user `get_list` drops the image column, so every row has one value
and `dict()` raises. On production that broke Assign To for Victor (Operations).

Run: bench --site <site> run-tests --app cgm_shipping --module cgm_shipping.tests.test_link_search_images
"""

import unittest
from unittest.mock import patch

import frappe
import frappe.desk.search as search

from cgm_shipping.cgm_worldwide_shipping.customizations import link_search_images as lsi

ROWS = [{"value": "declarant@cgmshipping.com"}]


def _upstream_add_images(get_list_rows):
	"""Frappe 16.60's add_images, fed what get_list returns for this user."""

	def add_images(rows, doctype):
		images = dict(get_list_rows)
		for row in rows:
			if images.get(row["value"]):
				row["image"] = images[row["value"]]

	return add_images


class TestLinkSearchImages(unittest.TestCase):
	def _install(self, original):
		"""Plant `original` as Frappe's add_images, wrap it, return the wrapper."""
		patcher = patch.object(search, "add_images", original, create=True)
		patcher.start()
		self.addCleanup(patcher.stop)
		lsi.ensure_link_search_images_guard()
		return search.add_images

	def test_select_only_user_gets_results_without_photos(self):
		# get_list dropped the image column: one value per row, as on production
		wrapped = self._install(_upstream_add_images([("declarant@cgmshipping.com",)]))
		rows = [dict(r) for r in ROWS]
		with patch.object(lsi, "image_field_readable", return_value=False):
			wrapped(rows, "User")
		self.assertNotIn("image", rows[0])

	def test_unguarded_upstream_code_crashes_as_on_production(self):
		original = _upstream_add_images([("declarant@cgmshipping.com",)])
		with self.assertRaisesRegex(ValueError, "has length 1; 2 is required"):
			original([dict(r) for r in ROWS], "User")

	def test_user_who_may_read_still_gets_photos(self):
		wrapped = self._install(_upstream_add_images([("declarant@cgmshipping.com", "/files/d.png")]))
		rows = [dict(r) for r in ROWS]
		with patch.object(lsi, "image_field_readable", return_value=True):
			wrapped(rows, "User")
		self.assertEqual(rows[0]["image"], "/files/d.png")

	def test_wraps_once_per_process(self):
		wrapped = self._install(_upstream_add_images([]))
		lsi.ensure_link_search_images_guard()
		self.assertIs(search.add_images, wrapped)

	def test_noop_on_frappe_without_add_images(self):
		saved = search.__dict__.pop("add_images", None)
		try:
			lsi.ensure_link_search_images_guard()
			self.assertFalse(hasattr(search, "add_images"))
		finally:
			if saved is not None:
				search.add_images = saved

	def test_readable_follows_get_list_column_rules(self):
		with patch("frappe.model.get_permitted_fields", return_value=["name", "full_name"]):
			self.assertFalse(lsi.image_field_readable("User"))
		with patch("frappe.model.get_permitted_fields", return_value=["name", "user_image"]):
			self.assertTrue(lsi.image_field_readable("User"))

	def test_hook_is_registered(self):
		self.assertIn(
			"cgm_shipping.cgm_worldwide_shipping.customizations.link_search_images.ensure_link_search_images_guard",
			frappe.get_hooks("before_request"),
		)
