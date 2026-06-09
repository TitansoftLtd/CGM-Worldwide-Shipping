"""Guard against dangling imports.

Every Python module in the app is imported; an ImportError (e.g. a `from ...`
pointing at a module that was deleted/renamed) fails the test. This catches the
class of breakage where a cleanup removes a module but leaves its callers behind.

Run: bench --site <site> run-tests --app cgm_shipping --module cgm_shipping.tests.test_module_imports
"""

import importlib
import os
import unittest

import cgm_shipping

APP_PKG_ROOT = os.path.dirname(cgm_shipping.__file__)  # .../apps/cgm_shipping/cgm_shipping
APP_REPO_ROOT = os.path.dirname(APP_PKG_ROOT)  # .../apps/cgm_shipping


class TestModuleImports(unittest.TestCase):
	def test_all_modules_import(self):
		failures = []
		for dirpath, _dirnames, filenames in os.walk(APP_PKG_ROOT):
			if "__pycache__" in dirpath:
				continue
			for filename in filenames:
				if not filename.endswith(".py"):
					continue
				rel = os.path.relpath(os.path.join(dirpath, filename), APP_REPO_ROOT)
				module = rel[:-3].replace(os.sep, ".")
				if module.endswith(".__init__"):
					module = module[: -len(".__init__")]
				if module.endswith("test_module_imports"):
					continue  # don't re-import self
				try:
					importlib.import_module(module)
				except Exception as exc:  # noqa: BLE001 - we want every failure
					failures.append(f"{module}: {type(exc).__name__}: {exc}")

		self.assertEqual(
			[],
			failures,
			"Modules failed to import (dangling imports?):\n" + "\n".join(failures),
		)
