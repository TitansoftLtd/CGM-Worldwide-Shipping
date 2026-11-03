"""One map decides which Container Tracker fields reach which step's task grid.

It used to be written out four times, which is how gate_in_date_depot went missing
from the seed query. These tests hold every reader to the one map.

They also pin that Load trucks shows and syncs the transport details without being
gated on them. Only Book Trucks refuses to complete without them.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import task_container_updates as tcu
from cgm_shipping.cgm_worldwide_shipping.customizations.constants import (
    CONTAINER_STEP_BOOK_TRUCKS,
    CONTAINER_STEP_GATE_OUT,
)

SEQ = {
    "custom_vessel_arrival_task_seq": 12,
    "custom_field_clearance_task_seq": 17,
    "custom_book_trucks_task_seq": 20,
    "custom_gate_out_task_seq": 21,
    "custom_monitor_delivery_task_seq": 22,
    "custom_offload_task_seq": 23,
    "custom_empty_return_task_seq": 24,
    "custom_interchange_task_seq": 25,
}


def _seq(fieldname):
    return SEQ.get(fieldname, 0)


def _row(**values):
    row = frappe._dict(values)
    row.set = lambda f, v: row.__setitem__(f, v)
    return row


class TestOneSourceForTheMap(unittest.TestCase):
    """Every reader of the pairing reads the same map."""

    def test_the_live_sync_and_the_finished_backfill_agree(self):
        with patch.object(tcu, "get_container_task_sequence", _seq):
            self.assertEqual(tcu._finished_backfill_fields(), tcu._sync_fields_by_seq())

    def test_the_task_to_tracker_push_covers_every_synced_field(self):
        """A field pushed to the grid must travel back, or grid edits vanish."""
        with patch.object(tcu, "get_container_task_sequence", _seq):
            sync = tcu._sync_fields_by_seq()
            pairs = tcu._seq_field_map()
        for seq, fields in sync.items():
            back = {tracker_field for _task_field, tracker_field in pairs.get(seq, [])}
            for field in fields:
                self.assertIn(
                    field,
                    back,
                    f"{field} reaches the grid for seq {seq} but cannot travel back",
                )

    def test_renamed_pairs_travel_one_way_only(self):
        """Names differ, so the reverse sync cannot match them."""
        with patch.object(tcu, "get_container_task_sequence", _seq):
            sync = tcu._sync_fields_by_seq()
            pairs = tcu._seq_field_map()
        offload = SEQ["custom_offload_task_seq"]
        self.assertIn(("container_emptied_location", "delivery_location"), pairs[offload])
        self.assertNotIn("container_emptied_location", sync[offload])

    def test_the_seed_query_selects_every_field_the_map_uses(self):
        """The gate_in_date_depot bug: a field the seed never read read as blank."""
        with patch.object(tcu, "get_container_task_sequence", _seq):
            sync = tcu._sync_fields_by_seq()
        selected = set(tcu.TRACKER_SEED_FIELDS)
        for seq, fields in sync.items():
            for field in fields:
                self.assertIn(
                    field,
                    selected,
                    f"{field} is seeded for seq {seq} but TRACKER_SEED_FIELDS never reads it",
                )


class TestLoadTrucksCarriesTheTransportDetails(unittest.TestCase):
    """The client asked for the booked truck to show on the exit step."""

    def test_gate_out_syncs_transporter_truck_and_driver(self):
        with patch.object(tcu, "get_container_task_sequence", _seq):
            fields = tcu._sync_fields_by_seq()[SEQ["custom_gate_out_task_seq"]]
        for field in tcu.TRANSPORT_TRACKER_FIELDS:
            self.assertIn(field, fields)

    def test_gate_out_keeps_its_own_fields_too(self):
        with patch.object(tcu, "get_container_task_sequence", _seq):
            fields = tcu._sync_fields_by_seq()[SEQ["custom_gate_out_task_seq"]]
        for field in ("gate_out_date_port", "free_days_start_date", "free_days_end_date"):
            self.assertIn(field, fields)

    def test_showing_the_details_is_not_the_same_as_requiring_them(self):
        """Book Trucks waits for the four fields. Load trucks only displays them."""
        required = tcu.DEFAULT_CONTAINER_STEP_REQUIREMENTS
        self.assertEqual(required[CONTAINER_STEP_BOOK_TRUCKS], tcu.TRANSPORT_TRACKER_FIELDS)
        self.assertEqual(required[CONTAINER_STEP_GATE_OUT], ("gate_out_date_port",))


class TestSeedingARow(unittest.TestCase):
    """The per-step branches collapsed into one loop; behaviour must be identical."""

    def _prefill(self, row, tracker, seq, **kw):
        with patch.object(tcu, "get_container_task_sequence", _seq):
            return tcu._prefill_row_from_tracker(row, tracker, seq, **kw)

    def test_a_gate_out_row_is_seeded_with_the_booked_truck(self):
        row = _row(current_status=None)
        tracker = {
            "status": "Released / In Transit",
            "transporter": "ACME",
            "truck_number": "KBX 123A",
            "driver_name": "J. Mwangi",
            "driver_contact": "0712345678",
            "gate_out_date_port": "2026-10-01",
        }
        self.assertTrue(self._prefill(row, tracker, SEQ["custom_gate_out_task_seq"]))
        self.assertEqual(row.truck_number, "KBX 123A")
        self.assertEqual(row.driver_contact, "0712345678")
        self.assertEqual(row.gate_out_date_port, "2026-10-01")

    def test_a_cell_that_already_has_a_value_is_not_overwritten(self):
        row = _row(current_status="x", truck_number="KBX 999Z")
        tracker = {"status": "x", "truck_number": "KBX 123A", "driver_name": "J"}
        self._prefill(row, tracker, SEQ["custom_gate_out_task_seq"])
        self.assertEqual(row.truck_number, "KBX 999Z")
        self.assertEqual(row.driver_name, "J")

    def test_a_step_only_seeds_its_own_columns(self):
        row = _row(current_status="x")
        tracker = {"status": "x", "truck_number": "KBX 123A", "offloading_date": "2026-10-09"}
        self._prefill(row, tracker, SEQ["custom_offload_task_seq"])
        self.assertEqual(row.offloading_date, "2026-10-09")
        self.assertIsNone(row.get("truck_number"))

    def test_vessel_arrival_still_falls_back_to_ata(self):
        row = _row(current_status="x")
        tracker = {"status": "x", "discharging_date": None, "ata": "2026-09-30"}
        self.assertTrue(self._prefill(row, tracker, SEQ["custom_vessel_arrival_task_seq"]))
        self.assertEqual(row.discharging_date, "2026-09-30")

    def test_vessel_arrival_still_overwrites_because_the_project_owns_it(self):
        """Project port-arrival confirm is the source of truth here."""
        row = _row(current_status="x", discharging_date="2026-09-01")
        tracker = {"status": "x", "discharging_date": "2026-09-30"}
        self.assertTrue(self._prefill(row, tracker, SEQ["custom_vessel_arrival_task_seq"]))
        self.assertEqual(row.discharging_date, "2026-09-30")

    def test_the_shipping_line_branch_still_wins_over_the_step_columns(self):
        """A deposit task takes the Bill of Lading figure."""
        row = _row(current_status="x")
        tracker = {"status": "x", "container_number": "ABCD1234567", "truck_number": "KBX 1"}
        with patch.object(
            tcu,
            "_bl_deposit_by_container_number",
            return_value={"ABCD1234567": {"deposit_amount": 500.0}},
        ):
            self._prefill(
                row,
                tracker,
                SEQ["custom_gate_out_task_seq"],
                project="PROJ-1",
                shipping_line=True,
            )
        self.assertEqual(row.deposit_amount, 500.0)
        self.assertIsNone(row.get("truck_number"))

    def test_the_current_status_is_always_refreshed(self):
        row = _row(current_status="old")
        self.assertTrue(self._prefill(row, {"status": "new"}, SEQ["custom_offload_task_seq"]))
        self.assertEqual(row.current_status, "new")


class _FakeTask:
    def __init__(self, seq, rows=None):
        self.seq = seq
        self.project = "PROJ-1"
        self.rows = list(rows or [])
        self.meta = frappe._dict(has_field=lambda f: True)

    def is_new(self):
        return False

    def get(self, field, default=None):
        if field == tcu.TASK_CONTAINER_UPDATES_FIELD:
            return self.rows
        return {"project": self.project}.get(field, default)

    def append(self, _field, data):
        row = _row(**data)
        self.rows.append(row)
        return row


class TestSeedingANewRow(unittest.TestCase):
    """New rows used to skip the prefill and be born blank on four of the steps."""

    def _seed(self, seq, tracker):
        task = _FakeTask(seq)
        with (
            patch.object(tcu, "get_container_task_sequence", _seq),
            patch.object(tcu, "_container_seq", return_value=seq),
            patch.object(tcu, "is_container_update_task", return_value=True),
            patch.object(tcu, "is_shipping_line_deposit_mirror_task", return_value=False),
            patch.object(tcu, "tracker_row_cargo_size", return_value="40"),
            patch.object(frappe, "get_all", return_value=[frappe._dict(tracker)]),
        ):
            changed = tcu.seed_container_update_rows(task)
        return changed, task.rows

    def test_a_new_gate_out_row_carries_the_booked_truck(self):
        changed, rows = self._seed(
            SEQ["custom_gate_out_task_seq"],
            {
                "name": "CT-1",
                "container_number": "ABCD1234567",
                "status": "Released / In Transit",
                "transporter": "ACME",
                "truck_number": "KBX 123A",
                "driver_name": "J. Mwangi",
                "driver_contact": "0712345678",
                "gate_out_date_port": "2026-10-01",
            },
        )
        self.assertTrue(changed)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].truck_number, "KBX 123A")
        self.assertEqual(rows[0].driver_contact, "0712345678")
        self.assertEqual(rows[0].gate_out_date_port, "2026-10-01")

    def test_a_new_empty_return_row_carries_the_depot_gate_in(self):
        _changed, rows = self._seed(
            SEQ["custom_empty_return_task_seq"],
            {
                "name": "CT-1",
                "container_number": "ABCD1234567",
                "status": "Empty Returned",
                "actual_empty_return": "2026-10-20",
                "gate_in_date_depot": "2026-10-21",
            },
        )
        self.assertEqual(rows[0].actual_empty_return, "2026-10-20")
        self.assertEqual(rows[0].gate_in_date_depot, "2026-10-21")

    def test_a_new_row_still_records_the_container_identity(self):
        _changed, rows = self._seed(
            SEQ["custom_offload_task_seq"],
            {"name": "CT-1", "container_number": "ABCD1234567", "status": "Cargo Offloaded"},
        )
        self.assertEqual(rows[0].container_tracker, "CT-1")
        self.assertEqual(rows[0].container_number, "ABCD1234567")
        self.assertEqual(rows[0].cargo_size, "40")
        self.assertEqual(rows[0].current_status, "Cargo Offloaded")
