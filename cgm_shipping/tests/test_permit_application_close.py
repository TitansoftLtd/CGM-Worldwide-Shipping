"""A permit application closes once Finance has finished, not only at that instant.

close_permit_application_when_finance_done fires on the Finance task's save and
nothing else. If the application was not ready at that moment - a certificate still
to come, or a row not yet marked Foreign - nothing looked again, and it sat Open
with Finance long since closed. TASK-2026-00889 on production is exactly that: its
partner TASK-2026-00890 is Completed while it stays Open.

The rule for what a permit needs is NOT restated here. Both directions ask
validate_permit_application_can_complete, because a second copy would drift and a
Foreign permit would start waiting for an invoice it never gets.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import workflow as wf


class _Task:
    def __init__(self, name="TASK-APP", status="Open"):
        self.name = name
        self.status = status


def _run(
    *,
    is_application=True,
    status="Open",
    client_pays=False,
    finance_name="TASK-FIN",
    finance_status="Completed",
    gate_raises=False,
    pending=([], [], []),
):
    written = {}

    def set_value(doctype, name, values, **kw):
        written[name] = values

    def get_value(doctype, name, fields, **kw):
        return frappe._dict(
            {"status": finance_status, "completed_by": "fin@x", "completed_on": "2026-11-04 10:00:00"}
        )

    def gate(_task):
        if gate_raises:
            raise frappe.ValidationError("not ready")

    with (
        patch.object(wf, "is_permit_application_task_doc", return_value=is_application),
        patch.object(wf, "task_client_paid_directly", return_value=client_pays),
        patch.object(wf, "finance_permit_task_for_application", return_value=finance_name),
        patch.object(wf, "merge_project_permits_into_application_task", return_value=None),
        patch.object(wf, "validate_permit_application_can_complete", side_effect=gate),
        patch.object(wf, "permit_rows_pending_verification", return_value=pending),
        patch.object(frappe.db, "get_value", side_effect=get_value),
        patch.object(frappe.db, "set_value", side_effect=set_value),
        patch.object(frappe, "clear_document_cache", return_value=None),
    ):
        closed = wf.close_permit_application_if_finance_already_done(_Task(status=status))
    return closed, written


class TestItClosesWhenFinanceAlreadyFinished(unittest.TestCase):
    def test_a_ready_application_closes(self):
        closed, written = _run()
        self.assertTrue(closed)
        self.assertEqual(written["TASK-APP"]["status"], "Completed")

    def test_it_records_who_finished_it_and_when(self):
        """Taken from the Finance task, not from whoever happened to open the form."""
        _closed, written = _run()
        self.assertEqual(written["TASK-APP"]["completed_by"], "fin@x")
        self.assertEqual(written["TASK-APP"]["completed_on"], "2026-11-04 10:00:00")
        self.assertEqual(written["TASK-APP"]["progress"], 100)


class TestItRefusesEverythingElse(unittest.TestCase):
    def test_not_while_finance_is_still_open(self):
        closed, written = _run(finance_status="Open")
        self.assertFalse(closed)
        self.assertEqual(written, {})

    def test_not_when_the_gate_says_it_is_not_ready(self):
        """A Foreign row with no certificate lands here, and must not close."""
        closed, written = _run(gate_raises=True)
        self.assertFalse(closed)
        self.assertEqual(written, {})

    def test_not_while_an_invoice_or_receipt_is_unverified(self):
        closed, written = _run(pending=(["Porthealth"], [], []))
        self.assertFalse(closed)
        self.assertEqual(written, {})

    def test_not_on_the_client_pays_path(self):
        """The declarant closes those themselves, as before."""
        closed, _written = _run(client_pays=True)
        self.assertFalse(closed)

    def test_not_when_there_is_no_finance_partner(self):
        closed, _written = _run(finance_name=None)
        self.assertFalse(closed)

    def test_not_on_a_task_that_is_not_a_permit_application(self):
        closed, _written = _run(is_application=False)
        self.assertFalse(closed)

    def test_not_on_one_already_completed(self):
        closed, _written = _run(status="Completed")
        self.assertFalse(closed)

    def test_not_on_a_cancelled_one(self):
        closed, _written = _run(status="Cancelled")
        self.assertFalse(closed)


class TestThereIsOnlyOneRule(unittest.TestCase):
    """Two copies of "what a permit needs" is how Foreign broke in the first place."""

    def test_both_directions_ask_the_same_gate(self):
        import inspect

        shared = inspect.getsource(wf._close_permit_application_if_ready)
        self.assertIn("validate_permit_application_can_complete", shared)
        for fn in (
            wf.close_permit_application_when_finance_done,
            wf.close_permit_application_if_finance_already_done,
        ):
            with self.subTest(fn=fn.__name__):
                self.assertIn("_close_permit_application_if_ready", inspect.getsource(fn))

    def test_neither_direction_re_decides_what_a_permit_needs(self):
        import inspect

        for fn in (
            wf.close_permit_application_when_finance_done,
            wf.close_permit_application_if_finance_already_done,
        ):
            src = inspect.getsource(fn)
            with self.subTest(fn=fn.__name__):
                self.assertNotIn("permit_requires_payment", src)
                self.assertNotIn("payment_invoice", src)

    def test_it_is_a_patch_and_not_something_that_fires_on_opening_a_task(self):
        """Closing a task because somebody opened it is a nasty surprise.

        It runs once from a migrate patch. The forward path is unchanged: Finance
        completing still closes a ready application, which is a deliberate act and
        no surprise to anyone.
        """
        import inspect

        from cgm_shipping.cgm_worldwide_shipping.customizations import task_status
        from cgm_shipping.patches import close_permit_applications_finance_finished as patch

        self.assertNotIn(
            "close_permit_application_if_finance_already_done",
            inspect.getsource(task_status),
        )
        self.assertIn(
            "close_permit_application_if_finance_already_done", inspect.getsource(patch)
        )

    def test_the_patch_is_registered_to_run(self):
        from pathlib import Path

        import cgm_shipping

        listed = (
            Path(cgm_shipping.__file__).parent / "patches.txt"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "cgm_shipping.patches.close_permit_applications_finance_finished", listed
        )

    def test_the_patch_only_looks_at_open_permit_applications(self):
        import inspect

        from cgm_shipping.patches import close_permit_applications_finance_finished as patch

        src = inspect.getsource(patch.execute)
        self.assertIn('"custom_task_role": "Permit Application"', src)
        self.assertIn("OPEN_STATES", src)


class TestChangingAPermitToForeignMidway(unittest.TestCase):
    """Marking a permit Foreign halfway through must reach the Finance task.

    It did not. `origin` was missing from the permit fingerprint, so the flip saved
    silently and the application-to-finance sync never ran. Finance went on holding
    a Local row owing a receipt that was never coming, and the declarant's task
    could not close. Four pairs on production were stuck that way.
    """

    def test_origin_is_part_of_the_permit_fingerprint(self):
        class _Doc:
            def __init__(self, origin):
                self.rows = [
                    frappe._dict(
                        permit_type="KEBS", origin=origin, payment_invoice="/f/a.pdf"
                    )
                ]

            def get(self, _field, _default=None):
                return self.rows

        before = wf.permit_work_fingerprint(_Doc("Local"))
        after = wf.permit_work_fingerprint(_Doc("Foreign"))
        self.assertTrue(before, "the fingerprint should not be empty")
        self.assertNotEqual(before, after, "flipping origin must count as permit work")

    def test_the_sync_drops_a_row_the_declarant_marked_foreign(self):
        """It used to trust the finance copy's own origin, which was the stale one."""
        import inspect

        src = inspect.getsource(wf.sync_permit_invoices_to_finance_task)
        self.assertIn("foreign_types", src)
        self.assertIn("in foreign_types", src)

    def test_a_foreign_row_is_never_sent_to_finance_in_the_first_place(self):
        from cgm_shipping.cgm_worldwide_shipping.doctype.permit_register.permit_register import (
            permit_requires_payment,
        )

        self.assertFalse(permit_requires_payment(frappe._dict(origin="Foreign")))
        self.assertTrue(permit_requires_payment(frappe._dict(origin="Local")))
        self.assertTrue(permit_requires_payment(frappe._dict()))

    def test_the_backfill_patch_is_registered(self):
        from pathlib import Path

        import cgm_shipping

        listed = (Path(cgm_shipping.__file__).parent / "patches.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("cgm_shipping.patches.drop_stale_foreign_permit_rows", listed)

    def test_the_patch_reuses_the_sync_and_the_gate(self):
        """It must not re-decide what a permit needs; that is how Foreign broke."""
        import inspect

        from cgm_shipping.patches import drop_stale_foreign_permit_rows as patch

        src = inspect.getsource(patch.execute)
        self.assertIn("sync_permit_invoices_to_finance_task", src)
        self.assertIn("close_permit_application_if_finance_already_done", src)
        self.assertNotIn("payment_receipt", src)
