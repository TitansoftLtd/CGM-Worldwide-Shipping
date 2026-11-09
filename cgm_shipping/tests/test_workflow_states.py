"""The shipment stepper reads the workflow's state rows, which repeat.

A Frappe workflow names one editing role per row, so letting a second role edit a
state means a second row for that state. Read raw, the stepper drew every state
twice and the progress index pointed at the wrong step.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.workflow import (
    get_sea_import_workflow_states,
)

# Uncached: request_cache would hand back another test's answer.
states_of = get_sea_import_workflow_states.__wrapped__


def _rows(*states):
    def get_all(doctype, **kw):
        return [frappe._dict({"state": s}) for s in states]

    return patch.object(frappe, "get_all", side_effect=get_all)


class TestSeaImportWorkflowStates(unittest.TestCase):
    def setUp(self):
        self.exists = patch.object(frappe.db, "exists", return_value=True)
        self.exists.start()
        self.addCleanup(self.exists.stop)

    def test_a_state_named_once_per_role_is_listed_once(self):
        with _rows("Draft", "Draft", "UCR Paid", "UCR Paid", "UCR Paid"):
            self.assertEqual(states_of(), ["Draft", "UCR Paid"])

    def test_the_chart_order_survives(self):
        with _rows("Draft", "Documents Received", "Draft", "UCR Paid", "Documents Received"):
            self.assertEqual(states_of(), ["Draft", "Documents Received", "UCR Paid"])

    def test_blank_rows_are_ignored(self):
        with _rows("Draft", "", None, "Completed"):
            self.assertEqual(states_of(), ["Draft", "Completed"])

    def test_no_rows_falls_back_to_the_seed_list(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
            DEFAULT_SEA_IMPORT_WORKFLOW_STATES,
        )

        with _rows():
            self.assertEqual(states_of(), list(DEFAULT_SEA_IMPORT_WORKFLOW_STATES))


if __name__ == "__main__":
    unittest.main()
