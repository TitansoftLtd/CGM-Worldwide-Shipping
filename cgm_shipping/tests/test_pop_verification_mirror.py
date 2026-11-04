"""A POP Finance has verified must say so on the declarant's task too.

The invoice row had a mirror and the receipt row had a mirror. The POP row, which
only Shipping Line carries, had none, so Finance ticked it on their task and the
declarant's copy read "Pending Verification" for good. Measured on real data before
the fix: 19 of 41 application tasks disagreed with their finance twin.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import application_finance as af

SHIPPING_LINE = af.APPLICATION_FINANCE_PROFILES["Shipping Line Application"]
UCR = af.APPLICATION_FINANCE_PROFILES["UCR Application"]


def _line(**kw):
    row = frappe._dict({"verified": 0, "verified_by": None, "verified_on": None})
    row.update(kw)
    return row


class _FinanceTask:
    def __init__(self, project="PROJ-1"):
        self.project = project
        self.name = "TASK-FIN"


def _run(profile, pop_line, *, app_line_name="LINE-APP", app_verified=0):
    """Drive the mirror with the surrounding lookups stubbed out."""
    written = {}

    def set_value(doctype, name, values, **kw):
        written[name] = values

    def get_value(doctype, filters, fieldname, **kw):
        if fieldname == "name":
            return app_line_name
        if fieldname == "verified":
            return app_verified
        return None

    with (
        patch.object(af, "task_matches_application_finance", return_value=True),
        patch.object(af, "task_has_finance_table", return_value=True),
        patch.object(af, "get_application_task", return_value="TASK-APP"),
        patch.object(af, "get_pop_line", return_value=pop_line),
        patch.object(frappe.db, "get_value", side_effect=get_value),
        patch.object(frappe.db, "set_value", side_effect=set_value),
    ):
        changed = af.sync_pop_verification_to_application_task(_FinanceTask(), profile)
    return changed, written


class TestThePopMirror(unittest.TestCase):
    def test_a_verified_pop_reaches_the_application_task(self):
        pop = _line(verified=1, verified_by="finance@x", verified_on="2026-11-03 10:00:00")
        changed, written = _run(SHIPPING_LINE, pop)
        self.assertTrue(changed)
        self.assertEqual(written["LINE-APP"]["verified"], 1)

    def test_it_carries_who_verified_it_and_when(self):
        """Without these the declarant sees a tick and no idea who put it there."""
        pop = _line(verified=1, verified_by="finance@x", verified_on="2026-11-03 10:00:00")
        _changed, written = _run(SHIPPING_LINE, pop)
        self.assertEqual(written["LINE-APP"]["verified_by"], "finance@x")
        self.assertEqual(written["LINE-APP"]["verified_on"], "2026-11-03 10:00:00")

    def test_an_unverified_pop_changes_nothing(self):
        changed, written = _run(SHIPPING_LINE, _line(verified=0))
        self.assertFalse(changed)
        self.assertEqual(written, {})

    def test_a_missing_pop_row_changes_nothing(self):
        changed, written = _run(SHIPPING_LINE, None)
        self.assertFalse(changed)
        self.assertEqual(written, {})

    def test_an_already_verified_application_row_is_not_rewritten(self):
        """Idempotent: re-running must not churn verified_by or the timestamp."""
        pop = _line(verified=1, verified_by="finance@x", verified_on="2026-11-03 10:00:00")
        changed, written = _run(SHIPPING_LINE, pop, app_verified=1)
        self.assertFalse(changed)
        self.assertEqual(written, {})


class TestOnlyShippingLineHasAPop(unittest.TestCase):
    def test_a_profile_without_a_pop_is_skipped(self):
        """UCR, Entry, KPA and CFS have no POP row, so there is nothing to mirror."""
        pop = _line(verified=1, verified_by="finance@x")
        changed, written = _run(UCR, pop)
        self.assertFalse(changed)
        self.assertEqual(written, {})

    def test_shipping_line_is_the_one_profile_that_carries_a_pop(self):
        with_pop = [
            name for name, p in af.APPLICATION_FINANCE_PROFILES.items() if p.requires_pop
        ]
        self.assertEqual(with_pop, ["Shipping Line Application"])


class TestItIsWiredIn(unittest.TestCase):
    """A mirror nothing calls is the bug it was written to fix."""

    def test_the_combined_sync_mirrors_all_three_rows(self):
        import inspect

        body = inspect.getsource(af.sync_status_from_finance_to_application)
        for fn in (
            "sync_invoice_verification_to_application_task",
            "sync_pop_verification_to_application_task",
            "sync_receipt_verification_to_application_task",
        ):
            self.assertIn(fn, body)

    def test_the_line_type_dispatch_handles_pop(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations import (
            workflow_application_finance as waf,
        )
        import inspect

        src = inspect.getsource(waf)
        self.assertIn('elif line_type == "POP":', src)
        self.assertIn("sync_pop_verification_to_application_task", src)
