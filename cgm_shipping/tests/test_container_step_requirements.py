"""A transport step stays open until every container carries the details that matter.

One tracker field used to close a step, and the rest of the row could stay blank:
Book Trucks signed itself off on a truck number alone, with no transporter and no
driver against the container. That is exactly the record wanted months later, when a
shipping line bills for demurrage and the question is who held the box and when the
depot took it back.

The agreed set is four fields on Book Trucks and the depot gate-in on Empty Return.
It is agreed, not fixed: Settings carries it so the next month of real shipments can
move it without a deploy.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import task_container_updates as tcu

SEQ = {
    "custom_track_eta_task_seq": 2,
    "custom_vessel_arrival_task_seq": 7,
    "custom_field_clearance_task_seq": 17,
    "custom_kpa_paid_task_seq": 19,
    "custom_book_trucks_task_seq": 20,
    "custom_gate_out_task_seq": 21,
    "custom_monitor_delivery_task_seq": 22,
    "custom_offload_task_seq": 23,
    "custom_empty_return_task_seq": 24,
    "custom_interchange_task_seq": 25,
}

TRACKER_LABELS = {
    "transporter": "Transporter",
    "truck_number": "Truck Number",
    "driver_name": "Driver Name",
    "driver_contact": "Driver Contact",
    "gate_out_date_port": "Gate Out Mombasa",
    "gate_in_date_warehouse": "Gate In Date (Clearance Station / Warehouse)",
    "delivery_location": "Clearance Station",
    "offloading_date": "Offloading Date",
    "actual_empty_return": "Actual Empty Return",
    "gate_in_date_depot": "Gate In Date Depot",
    "interchange_date": "Interchange Date",
    "interchange_document": "Interchange Document",
}

TRUCKS_BOOKED = {
    "transporter": "ACME Haulage",
    "truck_number": "KBX 123A",
    "driver_name": "J. Mwangi",
    "driver_contact": "0722000000",
}


def _meta(fields=None):
    known = TRACKER_LABELS if fields is None else {f: TRACKER_LABELS[f] for f in fields}
    return frappe._dict(
        has_field=lambda f: f in known,
        get_field=lambda f: frappe._dict(label=known[f]) if f in known else None,
    )


def _settings(rows=None, has_field=True):
    doc = frappe._dict(custom_container_step_requirements=rows or [])
    doc.meta = frappe._dict(has_field=lambda f: has_field)
    return doc


def _rule(step, field):
    return frappe._dict(container_step=step, tracker_field=field)


class _Env:
    """Settings, tracker meta and the configured sequence numbers, without a site."""

    def __init__(self, settings=None, tracker_fields=None, trackers=None):
        self.settings = settings if settings is not None else _settings()
        self.tracker_fields = tracker_fields
        self.trackers = trackers or []

    def __enter__(self):
        self._patches = [
            patch.object(tcu, "get_container_task_sequence", side_effect=lambda k: SEQ[k]),
            patch.object(frappe, "get_cached_doc", return_value=self.settings),
            patch.object(frappe, "get_meta", return_value=_meta(self.tracker_fields)),
            patch.object(frappe, "get_all", return_value=self.trackers),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def _tracker(number, **values):
    return frappe._dict({"name": f"CT-{number}", "container_number": number, **values})


class TestDefaultRequirements(unittest.TestCase):
    def test_book_trucks_needs_the_transporter_and_the_driver_not_just_the_truck(self):
        """The four fields the demurrage argument rests on."""
        with _Env():
            self.assertEqual(
                tcu.container_step_requirements()["Book Trucks"],
                ("transporter", "truck_number", "driver_name", "driver_contact"),
            )

    def test_empty_return_needs_the_depot_gate_in_as_well_as_the_return_date(self):
        with _Env():
            self.assertEqual(
                tcu.container_step_requirements()["Empty Return"],
                ("actual_empty_return", "gate_in_date_depot"),
            )

    def test_the_single_field_steps_are_unchanged(self):
        with _Env():
            requirements = tcu.container_step_requirements()
        self.assertEqual(requirements["Gate Out"], ("gate_out_date_port",))
        self.assertEqual(requirements["Monitor Delivery"], ("gate_in_date_warehouse",))
        self.assertEqual(requirements["Offload"], ("offloading_date",))

    def test_interchange_still_needs_the_date_and_the_receipt(self):
        with _Env():
            self.assertEqual(
                tcu.container_step_requirements()["Interchange"],
                ("interchange_date", "interchange_document"),
            )

    def test_steps_that_do_not_gate_are_not_listed(self):
        """ETA refresh, vessel arrival, field clearance and KPA close on their own terms."""
        with _Env():
            steps = tcu.container_step_requirements()
        for step in ("ETA Refresh", "Vessel Arrival", "Field Clearance", "KPA Paid"):
            self.assertNotIn(step, steps)


class TestTheGate(unittest.TestCase):
    def test_a_truck_without_a_driver_holds_book_trucks_open(self):
        trackers = [_tracker("MSCU1234567", truck_number="KBX 123A")]
        with _Env(trackers=trackers):
            missing = tcu._containers_missing_step("PROJ-1", SEQ["custom_book_trucks_task_seq"])
        self.assertEqual(missing, ["MSCU1234567"])

    def test_all_four_recorded_closes_it(self):
        trackers = [_tracker("MSCU1234567", **TRUCKS_BOOKED)]
        with _Env(trackers=trackers):
            missing = tcu._containers_missing_step("PROJ-1", SEQ["custom_book_trucks_task_seq"])
        self.assertEqual(missing, [])

    def test_a_returned_container_still_waits_on_the_depot_gate_in(self):
        trackers = [_tracker("TGHU9998877", actual_empty_return="2026-10-20")]
        with _Env(trackers=trackers):
            missing = tcu._containers_missing_step("PROJ-1", SEQ["custom_empty_return_task_seq"])
        self.assertEqual(missing, ["TGHU9998877"])

    def test_one_container_short_holds_the_step_for_the_whole_shipment(self):
        trackers = [
            _tracker("MSCU1234567", **TRUCKS_BOOKED),
            _tracker("TGHU9998877", truck_number="KBX 456B"),
        ]
        with _Env(trackers=trackers):
            missing = tcu._containers_missing_step("PROJ-1", SEQ["custom_book_trucks_task_seq"])
        self.assertEqual(missing, ["TGHU9998877"])

    def test_an_attachment_of_blanks_does_not_count_as_a_receipt(self):
        trackers = [_tracker("MSCU1234567", interchange_date="2026-10-22", interchange_document="   ")]
        with _Env(trackers=trackers):
            missing = tcu._containers_missing_step("PROJ-1", SEQ["custom_interchange_task_seq"])
        self.assertEqual(missing, ["MSCU1234567"])

    def test_a_container_with_no_number_is_named_by_its_tracker(self):
        trackers = [frappe._dict(name="CT-7", container_number=None)]
        with _Env(trackers=trackers):
            missing = tcu._containers_missing_step("PROJ-1", SEQ["custom_offload_task_seq"])
        self.assertEqual(missing, ["CT-7"])


class TestWhatTheBlockerSays(unittest.TestCase):
    def test_it_names_the_field_each_container_is_short_of(self):
        """"Fill in the details" sent people to a row where most cells were already full."""
        trackers = [
            _tracker("MSCU1234567", truck_number="KBX 123A", transporter="ACME Haulage"),
            _tracker("TGHU9998877", truck_number="KBX 456B", driver_name="J. Mwangi"),
        ]
        with _Env(trackers=trackers):
            lines = tcu._step_shortfall_lines("PROJ-1", SEQ["custom_book_trucks_task_seq"])
        self.assertEqual(
            lines,
            [
                "MSCU1234567 (Driver Name, Driver Contact)",
                "TGHU9998877 (Transporter, Driver Contact)",
            ],
        )

    def test_a_single_field_step_still_reads_as_the_container_alone(self):
        trackers = [_tracker("MSCU1234567")]
        with _Env(trackers=trackers):
            lines = tcu._step_shortfall_lines("PROJ-1", SEQ["custom_gate_out_task_seq"])
        self.assertEqual(lines, ["MSCU1234567"])

    def test_the_requirement_label_uses_the_names_on_the_tracker_form(self):
        """gate_out_date_port reads "Gate Out Mombasa" there, and nowhere else."""
        with _Env():
            self.assertEqual(
                tcu.container_step_requirement_label(SEQ["custom_gate_out_task_seq"]),
                "Gate Out Mombasa",
            )
            self.assertEqual(
                tcu.container_step_requirement_label(SEQ["custom_book_trucks_task_seq"]),
                "Transporter, Truck Number, Driver Name and Driver Contact",
            )
            self.assertEqual(
                tcu.container_step_requirement_label(SEQ["custom_interchange_task_seq"]),
                "Interchange Date and Interchange Document",
            )

    def test_a_task_on_a_step_that_does_not_gate_has_no_tracker_blocker(self):
        task = frappe._dict(custom_sequence_no=17, project="PROJ-1")
        with _Env():
            self.assertEqual(tcu.transport_step_tracker_blockers(task), ("", []))


class TestSettingsOverride(unittest.TestCase):
    def test_settings_replaces_the_default_for_that_step_only(self):
        rows = [_rule("Book Trucks", "truck_number")]
        with _Env(settings=_settings(rows)):
            requirements = tcu.container_step_requirements()
        self.assertEqual(requirements["Book Trucks"], ("truck_number",))
        self.assertEqual(requirements["Empty Return"], ("actual_empty_return", "gate_in_date_depot"))

    def test_settings_can_ask_for_more_than_the_default(self):
        rows = [
            _rule("Monitor Delivery", "gate_in_date_warehouse"),
            _rule("Monitor Delivery", "delivery_location"),
        ]
        with _Env(settings=_settings(rows)):
            self.assertEqual(
                tcu.container_step_requirements()["Monitor Delivery"],
                ("gate_in_date_warehouse", "delivery_location"),
            )

    def test_an_empty_table_means_the_defaults_never_nothing(self):
        with _Env(settings=_settings([])):
            self.assertEqual(
                tcu.container_step_requirements()["Book Trucks"],
                ("transporter", "truck_number", "driver_name", "driver_contact"),
            )

    def test_the_same_field_twice_is_asked_for_once(self):
        rows = [_rule("Offload", "offloading_date"), _rule("Offload", "offloading_date")]
        with _Env(settings=_settings(rows)):
            self.assertEqual(tcu.container_step_requirements()["Offload"], ("offloading_date",))

    def test_a_field_the_tracker_does_not_have_is_ignored_not_waited_for(self):
        """Otherwise the step hangs for good, with nowhere for anyone to go and fill it."""
        rows = [_rule("Offload", "a_field_that_went_away")]
        with _Env(settings=_settings(rows)):
            self.assertEqual(tcu.container_step_requirements()["Offload"], ("offloading_date",))

    def test_a_blank_row_is_skipped(self):
        rows = [_rule("", ""), _rule("Offload", "")]
        with _Env(settings=_settings(rows)):
            self.assertEqual(tcu.container_step_requirements()["Offload"], ("offloading_date",))

    def test_the_defaults_gate_when_settings_cannot_be_read(self):
        """Mid-install or mid-patch, a step must not quietly stop checking."""
        with _Env():
            with patch.object(frappe, "get_cached_doc", side_effect=Exception("no settings yet")):
                self.assertEqual(
                    tcu.container_step_requirements()["Empty Return"],
                    ("actual_empty_return", "gate_in_date_depot"),
                )

    def test_an_older_site_without_the_table_uses_the_defaults(self):
        with _Env(settings=_settings([], has_field=False)):
            self.assertEqual(
                tcu.container_step_requirements()["Book Trucks"],
                ("transporter", "truck_number", "driver_name", "driver_contact"),
            )


class TestSeeding(unittest.TestCase):
    def test_the_grid_reads_every_field_a_step_can_require(self):
        """A gate field the seed query never selected would read as permanently blank."""
        with _Env():
            required = {f for fields in tcu.container_step_requirements().values() for f in fields}
        self.assertTrue(
            required <= set(tcu.TRACKER_SEED_FIELDS),
            f"not selected when seeding task rows: {sorted(required - set(tcu.TRACKER_SEED_FIELDS))}",
        )


class _SettingsDoc:
    """Just enough of the Single to seed and validate rows against."""

    def __init__(self, rows=None, has_field=True):
        self.rows = list(rows or [])
        self.meta = frappe._dict(has_field=lambda f: has_field)
        self.flags = frappe._dict()
        self.saved = 0

    def get(self, field, default=None):
        return self.rows

    def set(self, field, value):
        self.rows = value

    def append(self, field, values):
        row = frappe._dict(values)
        self.rows.append(row)
        return row

    def save(self, **kwargs):
        self.saved += 1


class TestSeedingTheTable(unittest.TestCase):
    def test_an_empty_table_is_seeded_with_the_defaults(self):
        """An empty table told the reader nothing about what a step waits for."""
        settings = _SettingsDoc()
        with _Env():
            with (
                patch.object(frappe.db, "exists", return_value=True),
                patch.object(frappe, "get_single", return_value=settings),
            ):
                tcu.ensure_container_step_requirements()
        self.assertEqual(settings.saved, 1)
        booked = [r.tracker_field for r in settings.rows if r.container_step == "Book Trucks"]
        self.assertEqual(booked, ["transporter", "truck_number", "driver_name", "driver_contact"])
        # 4 on Book Trucks, 1 each on Gate Out, Monitor Delivery and Offload,
        # 2 on Empty Return and 2 on Interchange.
        self.assertEqual(len(settings.rows), 11)

    def test_each_seeded_row_carries_the_name_on_the_tracker_form(self):
        settings = _SettingsDoc()
        with _Env():
            with (
                patch.object(frappe.db, "exists", return_value=True),
                patch.object(frappe, "get_single", return_value=settings),
            ):
                tcu.ensure_container_step_requirements()
        by_field = {r.tracker_field: r.field_label for r in settings.rows}
        self.assertEqual(by_field["gate_out_date_port"], "Gate Out Mombasa")
        self.assertEqual(by_field["gate_in_date_depot"], "Gate In Date Depot")

    def test_rows_already_there_are_left_alone(self):
        """Rows someone has edited are theirs, not ours to restore."""
        settings = _SettingsDoc([_rule("Offload", "offloading_date")])
        with _Env():
            with (
                patch.object(frappe.db, "exists", return_value=True),
                patch.object(frappe, "get_single", return_value=settings),
            ):
                tcu.ensure_container_step_requirements()
        self.assertEqual(settings.saved, 0)
        self.assertEqual(len(settings.rows), 1)

    def test_seeding_the_table_changes_nothing_about_what_is_enforced(self):
        """Seeded rows must say exactly what the code would have gated on anyway."""
        settings = _SettingsDoc()
        with _Env():
            with (
                patch.object(frappe.db, "exists", return_value=True),
                patch.object(frappe, "get_single", return_value=settings),
            ):
                tcu.ensure_container_step_requirements()
            seeded = _settings(settings.rows)
            with patch.object(frappe, "get_cached_doc", return_value=seeded):
                after = tcu.container_step_requirements()
            with patch.object(frappe, "get_cached_doc", return_value=_settings([])):
                before = tcu.container_step_requirements()
        self.assertEqual(after, before)


class TestValidatingRows(unittest.TestCase):
    def test_the_label_is_written_from_the_tracker_not_typed_in(self):
        settings = _SettingsDoc([_rule("Gate Out", "gate_out_date_port")])
        with _Env():
            tcu.validate_container_step_requirement_rows(settings)
        self.assertEqual(settings.rows[0].field_label, "Gate Out Mombasa")

    def test_the_same_step_and_field_twice_is_kept_once(self):
        settings = _SettingsDoc(
            [_rule("Offload", "offloading_date"), _rule("Offload", "offloading_date")]
        )
        with _Env():
            tcu.validate_container_step_requirement_rows(settings)
        self.assertEqual(len(settings.rows), 1)

    def test_a_blank_row_is_dropped(self):
        settings = _SettingsDoc([_rule("Offload", "offloading_date"), _rule("", "")])
        with _Env():
            tcu.validate_container_step_requirement_rows(settings)
        self.assertEqual(len(settings.rows), 1)

    def test_a_field_the_tracker_does_not_have_is_refused_on_save(self):
        """Better to refuse the row than to accept a step nobody can ever close."""
        settings = _SettingsDoc([_rule("Offload", "nonexistent_field")])
        with _Env():
            with self.assertRaises(frappe.ValidationError):
                tcu.validate_container_step_requirement_rows(settings)

    def test_an_older_site_without_the_table_is_left_alone(self):
        settings = _SettingsDoc([], has_field=False)
        with _Env():
            tcu.validate_container_step_requirement_rows(settings)
        self.assertEqual(settings.rows, [])
