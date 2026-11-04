"""A container back late with its demurrage paid stops reading as an alarm.

Demurrage is the shipping line's charge for holding their box past the free days.
The line invoices it, the agent pays, and the exposure is then closed. Nothing
recorded that: 54 containers carried demurrage days and not one carried an amount,
an invoice or a payment, so a late container stayed red forever and ops moved the
free-days dates to quiet it. That dropped the status to "Discharged / At Port",
the colour of a box nobody has touched.

Settling is now recorded on the container, which gives it a calm status, freezes
the day count and leaves the lateness on the record.
"""

import unittest
from datetime import date
from unittest.mock import patch

from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
    CONTAINER_CLOSED_STATUSES,
    CONTAINER_STATUS_COLOUR,
    CONTAINER_STATUS_EMPTY_RETURNED,
    CONTAINER_STATUS_INTERCHANGE,
    CONTAINER_STATUS_PILL,
    CONTAINER_STATUS_RETURN_OVERDUE,
    CONTAINER_STATUS_RETURNED_LATE_SETTLED,
)
from cgm_shipping.cgm_worldwide_shipping.customizations import container_tracker as ct
from cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker import (
    _derive_alert_status,
    _derive_status,
    compute_container_metrics,
)

TODAY = date(2026, 11, 3)
FREE_END = date(2026, 9, 10)
RETURNED = date(2026, 9, 25)


def _status(**kw):
    args = dict(
        interchange=None, actual_return=None, expected_return=FREE_END, offloading=None,
        gate_in_wh=None, gate_out=None, discharging=date(2026, 9, 1), ata=None,
        ref_date=TODAY, settled=None,
    )
    args.update(kw)
    return _derive_status(**args)


class TestTheSettledStatus(unittest.TestCase):
    def test_back_late_and_paid_reads_as_settled(self):
        self.assertEqual(
            _status(actual_return=RETURNED, settled=date(2026, 10, 1)),
            CONTAINER_STATUS_RETURNED_LATE_SETTLED,
        )

    def test_back_late_and_unpaid_stays_as_empty_returned(self):
        self.assertEqual(_status(actual_return=RETURNED), CONTAINER_STATUS_EMPTY_RETURNED)

    def test_back_on_time_is_never_called_late(self):
        on_time = date(2026, 9, 9)
        self.assertEqual(
            _status(actual_return=on_time, settled=date(2026, 10, 1)),
            CONTAINER_STATUS_EMPTY_RETURNED,
        )

    def test_paying_without_returning_the_box_is_not_enough(self):
        """Settling closes the money, not the container. It is still out."""
        self.assertEqual(
            _status(settled=date(2026, 10, 1)), CONTAINER_STATUS_RETURN_OVERDUE
        )

    def test_the_interchange_still_wins(self):
        """Depot confirmed the empty back: that is the end of the job."""
        self.assertEqual(
            _status(interchange=date(2026, 10, 2), actual_return=RETURNED,
                    settled=date(2026, 10, 1)),
            CONTAINER_STATUS_INTERCHANGE,
        )

    def test_no_free_days_window_means_no_lateness_to_settle(self):
        self.assertEqual(
            _status(actual_return=RETURNED, expected_return=None, settled=date(2026, 10, 1)),
            CONTAINER_STATUS_EMPTY_RETURNED,
        )


class TestHowItLooks(unittest.TestCase):
    def test_the_colour_is_calm_not_an_alarm(self):
        self.assertEqual(CONTAINER_STATUS_COLOUR[CONTAINER_STATUS_RETURNED_LATE_SETTLED], "blue")
        self.assertEqual(CONTAINER_STATUS_COLOUR[CONTAINER_STATUS_RETURN_OVERDUE], "red")

    def test_the_pill_is_calm_too(self):
        self.assertEqual(CONTAINER_STATUS_PILL[CONTAINER_STATUS_RETURNED_LATE_SETTLED], "info")

    def test_it_counts_as_a_closed_container(self):
        """It is registered in the status table, so the counts pick it up."""
        self.assertIn(CONTAINER_STATUS_RETURNED_LATE_SETTLED, CONTAINER_CLOSED_STATUSES)


def _metrics(**kw):
    """compute_container_metrics reads the real clock, so pin it.

    These assertions compare against TODAY. Passing a _ref_date did nothing: the
    function calls today() itself, so the tests only agreed with it on the day they
    were written and broke at the next midnight.
    """
    data = {
        "free_days_start_date": date(2026, 9, 1),
        "free_days_end_date": FREE_END,
        "discharging_date": date(2026, 9, 1),
    }
    data.update(kw)
    with patch.object(ct, "today", lambda: TODAY.isoformat()):
        return compute_container_metrics(data)


class TestTheDayCount(unittest.TestCase):
    """The return stops the clock. Paying does not.

    Demurrage is settled as the container comes back, so the two happen together and
    the return is the real end of the charge. A settlement recorded while the box is
    still out therefore means more is owed, not less, and freezing the count there
    would have hidden live exposure.
    """

    def test_an_unreturned_unsettled_box_counts_against_today(self):
        days = _metrics()["demurrage_days"]
        self.assertEqual(days, (TODAY - FREE_END).days)

    def test_the_return_stops_it(self):
        days = _metrics(actual_empty_return=RETURNED)["demurrage_days"]
        self.assertEqual(days, (RETURNED - FREE_END).days)

    def test_settling_alone_does_not_stop_it(self):
        """The box is still out, so the days keep running and so does the bill."""
        settled = _metrics(demurrage_settled_on=date(2026, 10, 1))["demurrage_days"]
        self.assertEqual(settled, _metrics()["demurrage_days"])
        self.assertEqual(settled, (TODAY - FREE_END).days)

    def test_the_settlement_date_never_moves_the_count(self):
        paid_before_return = _metrics(
            actual_empty_return=RETURNED, demurrage_settled_on=date(2026, 9, 20)
        )["demurrage_days"]
        paid_after_return = _metrics(
            actual_empty_return=RETURNED, demurrage_settled_on=date(2026, 10, 1)
        )["demurrage_days"]
        self.assertEqual(paid_before_return, (RETURNED - FREE_END).days)
        self.assertEqual(paid_after_return, (RETURNED - FREE_END).days)


class TestTheFirstChargeableDay(unittest.TestCase):
    """demurrage_start_date was on the form, documented, and never filled in."""

    def test_it_is_the_day_after_the_free_days_end(self):
        self.assertEqual(_metrics()["demurrage_start_date"], date(2026, 9, 11))

    def test_it_is_blank_when_nothing_is_chargeable(self):
        early = _metrics(actual_empty_return=date(2026, 9, 5))
        self.assertEqual(early["demurrage_days"], 0)
        self.assertIsNone(early["demurrage_start_date"])


def _alert(**kw):
    args = dict(
        free_end=FREE_END, free_start=date(2026, 9, 1), gate_out=None, actual_return=None,
        interchange=None, expected_return=FREE_END, ref_date=TODAY, settled=None,
    )
    args.update(kw)
    return _derive_alert_status(**args)


class TestWhatTheAlertSays(unittest.TestCase):
    def test_late_and_settled_reads_calmly(self):
        msg = _alert(actual_return=RETURNED, settled=date(2026, 10, 1))
        self.assertIn("Settled", msg)
        self.assertTrue(msg.startswith("✅"), msg)

    def test_late_and_unsettled_still_warns(self):
        msg = _alert(actual_return=RETURNED)
        self.assertTrue(msg.startswith("⚠️"), msg)

    def test_the_frozen_count_is_the_lateness_not_a_growing_number(self):
        msg = _alert(actual_return=RETURNED, settled=date(2026, 10, 1))
        self.assertIn(str((RETURNED - FREE_END).days), msg)

    def test_paying_while_the_box_is_still_out_keeps_accruing(self):
        """More days out means more demurrage, whatever has been paid so far."""
        msg = _alert(settled=date(2026, 10, 1))
        self.assertTrue(msg.startswith("🔴") or msg.startswith("🚨"), msg)

    def test_on_time_is_unchanged(self):
        self.assertEqual(_alert(actual_return=date(2026, 9, 9)), "✅ Returned On Time")
