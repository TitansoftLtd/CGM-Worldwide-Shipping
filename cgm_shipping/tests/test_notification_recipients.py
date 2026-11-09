"""Nothing the system sends reaches a login that has been disabled.

Frappe drops a departed user from a role recipient, but not from a document field,
a static cc, or the assignee list - and our own routing resolves a role to its
assignees and appends their addresses itself, skipping Frappe's check. On production
that was 27 open assignments belonging to people who had gone, 26 on Tasks, with
their mobile numbers still on file.

The order is the point. A departed assignee is dropped when the assignee is chosen,
so a routed role still falls back to its live holders. Filtering only the finished
list would send the notification nowhere, which is how the leave watch notices went
missing in the first place.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import (
    notification_recipients as nr,
)
from cgm_shipping.cgm_worldwide_shipping.customizations import (
    notification_routing as nroute,
)


def _users(rows, employees=()):
    """Stub the disabled-User and Employee lookups with the fields each asks for."""

    def get_all(doctype, filters=None, fields=None, **kw):
        source = employees if doctype == "Employee" else rows
        return [frappe._dict({f: r.get(f) for f in (fields or [])}) for r in source]

    return patch.object(frappe, "get_all", side_effect=get_all)


GONE = [
    {"name": "gone@x.com", "email": "gone@x.com", "mobile_no": "0796770725", "phone": None},
    {"name": "left@x.com", "email": "personal@y.com", "mobile_no": None, "phone": "+254745519194"},
]


class TestAddresses(unittest.TestCase):
    def test_a_departed_address_is_dropped(self):
        with _users(GONE):
            self.assertEqual(nr.live_addresses(["live@x.com", "gone@x.com"]), ["live@x.com"])

    def test_their_other_address_is_dropped_too(self):
        """The login and the email on the User record are both theirs."""
        with _users(GONE):
            self.assertEqual(nr.live_addresses(["personal@y.com", "ok@x.com"]), ["ok@x.com"])

    def test_the_comparison_ignores_case_and_spacing(self):
        with _users(GONE):
            self.assertEqual(nr.live_addresses([" GONE@X.com "]), [])

    def test_somebody_who_is_not_a_user_is_left_alone(self):
        """A customer or a shipping line is not a login."""
        with _users(GONE):
            self.assertEqual(nr.live_addresses(["agent@maersk.com"]), ["agent@maersk.com"])

    def test_nobody_disabled_changes_nothing(self):
        with _users([]):
            self.assertEqual(nr.live_addresses(["a@x.com", "b@x.com"]), ["a@x.com", "b@x.com"])

    def test_an_empty_list_is_fine(self):
        with _users(GONE):
            self.assertEqual(nr.live_addresses(None), [])

    def test_a_lookup_failure_does_not_stop_live_people_being_told(self):
        with (
            patch.object(frappe, "get_all", side_effect=Exception("db down")),
            patch.object(frappe, "log_error"),
        ):
            self.assertEqual(nr.live_addresses(["a@x.com"]), ["a@x.com"])


class TestPhoneNumbers(unittest.TestCase):
    """SMS reaches a real handset, so a departed number matters more, not less."""

    def test_a_departed_number_is_dropped(self):
        with _users(GONE):
            self.assertEqual(nr.live_numbers(["0796770725", "0712000111"]), ["0712000111"])

    def test_the_same_number_in_international_form_is_dropped(self):
        with _users(GONE):
            self.assertEqual(nr.live_numbers(["+254796770725"]), [])
            self.assertEqual(nr.live_numbers(["254 796 770 725"]), [])

    def test_a_phone_field_counts_as_well_as_mobile(self):
        with _users(GONE):
            self.assertEqual(nr.live_numbers(["0745519194"]), [])

    def test_a_number_too_short_to_identify_is_left_alone(self):
        """Better a stray extension than silently dropping a live recipient."""
        with _users(GONE):
            self.assertEqual(nr.live_numbers(["4321"]), ["4321"])

    def test_the_number_on_their_employee_record_counts_too(self):
        """It is not the one on their User record.

        On production every departed employee's Employee cell number differs from
        their User mobile, and for one of them the real number is only on the
        Employee record. Reading User alone would have texted them.
        """
        with _users(GONE, employees=[{"cell_number": "0723498404"}]):
            self.assertEqual(nr.live_numbers(["0723498404"]), [])
            self.assertEqual(nr.live_numbers(["+254723498404"]), [])

    def test_a_live_number_survives_the_employee_lookup(self):
        with _users(GONE, employees=[{"cell_number": "0723498404"}]):
            self.assertEqual(nr.live_numbers(["0712000111"]), ["0712000111"])


class TestADepartedAssigneeFallsBackToTheRole(unittest.TestCase):
    """The notification must still reach somebody. This is the Mary bug, inverted."""

    def _assigned(self, allocated, gone):
        with (
            patch.object(frappe, "get_all", return_value=allocated),
            patch.object(nr, "gone_logins", return_value=gone),
        ):
            return nroute.assigned_users(frappe._dict(doctype="Task", name="TASK-1"), "Task")

    def test_a_departed_assignee_is_not_chosen(self):
        self.assertEqual(
            self._assigned(["gone@x.com", "live@x.com"], {"gone@x.com"}), ["live@x.com"]
        )

    def test_when_every_assignee_has_left_nobody_is_returned(self):
        """So resolve_role_recipients falls back to the role rather than to nobody."""
        self.assertEqual(self._assigned(["gone@x.com"], {"gone@x.com"}), [])

    def test_and_the_fallback_then_reaches_the_live_role(self):
        routes = {"Field Operations Officers": {"assigned_on": "Task", "fall_back_to_role": True}}
        with patch.object(nroute, "assigned_users", return_value=[]):
            self.assertIsNone(
                nroute.resolve_role_recipients(
                    frappe._dict(doctype="Task", name="TASK-1"),
                    "Field Operations Officers",
                    routes,
                )
            )


class TestEveryExitIsFiltered(unittest.TestCase):
    """Email and SMS, routed or not. A path left out is a path that leaks."""

    def test_both_methods_filter_on_every_return(self):
        import inspect

        for method, wanted in (
            (nroute.CGMNotification.get_list_of_recipients, "live_addresses"),
            (nroute.CGMNotification.get_receiver_list, "live_numbers"),
        ):
            src = inspect.getsource(method)
            returns = [ln for ln in src.splitlines() if ln.strip().startswith("return")]
            with self.subTest(method=method.__name__):
                self.assertTrue(returns)
                for ln in returns:
                    self.assertNotIn("super()", ln, f"unfiltered exit: {ln.strip()}")
                self.assertIn(wanted, src)


class TestTheEmailQueueBackstop(unittest.TestCase):
    """For mail queued outside a Notification: assignments, workflow, ERPNext's own."""

    def _queue(self, recipients, communication=None):
        doc = frappe._dict(
            communication=communication,
            reference_doctype="Leave Application",
            reference_name="HR-LAP-1",
            recipients=[frappe._dict(recipient=r) for r in recipients],
            error=None,
        )
        doc.set = lambda k, v, as_value=False: doc.__setitem__(k, v)
        return doc

    def _run(self, doc):
        with _users(GONE):
            nr.drop_disabled_from_email_queue(doc)
        return [r.recipient for r in doc.recipients]

    def test_a_departed_recipient_is_dropped(self):
        doc = self._queue(["live@x.com", "gone@x.com"])
        self.assertEqual(self._run(doc), ["live@x.com"])

    def test_the_last_one_going_leaves_a_row_that_explains_itself(self):
        doc = self._queue(["gone@x.com"])
        self.assertEqual(self._run(doc), [])
        self.assertIn("disabled", doc.error)

    def test_somebody_pressing_send_is_never_second_guessed(self):
        """A human addressed this. It goes where they addressed it."""
        doc = self._queue(["gone@x.com"], communication="COMM-1")
        self.assertEqual(self._run(doc), ["gone@x.com"])

    def test_an_untouched_list_is_left_exactly_as_it_was(self):
        doc = self._queue(["a@x.com", "b@x.com"])
        before = doc.recipients
        self.assertEqual(self._run(doc), ["a@x.com", "b@x.com"])
        self.assertIs(doc.recipients, before)
        self.assertIsNone(doc.error)


class TestTheSmsChokepoint(unittest.TestCase):
    """Every text in the app goes through deliver_sms, including ones whose numbers
    the caller worked out itself from the Employee record."""

    def _delivered(self, numbers, employees=()):
        from cgm_shipping.cgm_worldwide_shipping.customizations import workflow_sms

        sent = []
        with (
            _users(GONE, employees=employees),
            patch(
                "frappe.core.doctype.sms_settings.sms_settings._send_sms",
                side_effect=lambda ns, *a, **k: sent.extend(ns),
            ),
            patch.object(frappe, "log_error"),
        ):
            workflow_sms.deliver_sms(numbers, "text", source="probe")
        return sent

    def test_a_departed_handset_is_not_texted(self):
        self.assertEqual(self._delivered(["0796770725", "0712000111"]), ["0712000111"])

    def test_the_employee_record_number_is_not_texted_either(self):
        """This is the leave-approved text, which never sees the User mobile."""
        self.assertEqual(
            self._delivered(["0723498404"], employees=[{"cell_number": "0723498404"}]), []
        )

    def test_live_staff_are_still_texted(self):
        self.assertEqual(self._delivered(["0712000111"]), ["0712000111"])
