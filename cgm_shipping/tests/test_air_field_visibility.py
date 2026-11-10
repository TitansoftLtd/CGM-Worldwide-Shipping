"""An air shipment is not asked sea questions, and a declarant works the whole file.

The hiding lives in custom/project.json as depends_on, which syncs on migrate and
can be edited in Customize Form. These tests are what keeps that JSON honest.
"""

import json
import pathlib
import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import air_field_visibility as afv

CUSTOM = pathlib.Path(__file__).resolve().parents[1] / "cgm_worldwide_shipping/custom"
PROJECT_JSON = CUSTOM / "project.json"
OPPORTUNITY_JSON = CUSTOM / "opportunity.json"


def _project_fields() -> dict[str, dict]:
    data = json.loads(PROJECT_JSON.read_text())
    return {f["fieldname"]: f for f in data.get("custom_fields", [])}


def _project_fieldnames() -> set[str]:
    return set(_project_fields())


class TestTheHiddenList(unittest.TestCase):
    def test_every_hidden_field_exists_on_project(self):
        missing = sorted(set(afv.SEA_ONLY_PROJECT_FIELDS) - _project_fieldnames())
        self.assertEqual(missing, [], f"hidden fields not on Project: {missing}")

    def test_every_air_only_field_exists_on_project(self):
        missing = sorted(set(afv.AIR_ONLY_PROJECT_FIELDS) - _project_fieldnames())
        self.assertEqual(missing, [])

    def test_no_field_is_both_sea_only_and_air_only(self):
        self.assertEqual(
            set(afv.SEA_ONLY_PROJECT_FIELDS) & set(afv.AIR_ONLY_PROJECT_FIELDS), set()
        )

    def test_the_list_has_no_duplicates(self):
        names = afv.SEA_ONLY_PROJECT_FIELDS
        self.assertEqual(len(names), len(set(names)))

    def test_airline_and_air_waybill_are_left_alone(self):
        for keep in ("custom_airline", "custom_air_waybill"):
            self.assertNotIn(keep, afv.SEA_ONLY_PROJECT_FIELDS)

    def test_the_voyage_field_is_hidden_on_air(self):
        """No air replacement: the flight goes in Airline, as the Air Waybill does."""
        self.assertIn("custom_voyage_number", afv.SEA_ONLY_PROJECT_FIELDS)
        self.assertNotIn("custom_flight_number", afv.AIR_ONLY_PROJECT_FIELDS)


class TestTheJsonCarriesTheRule(unittest.TestCase):
    """Customize Form is where an admin looks, so the rule has to be there."""

    def test_every_sea_only_field_depends_on_not_air(self):
        fields = _project_fields()
        without = [
            name
            for name in afv.SEA_ONLY_PROJECT_FIELDS
            if afv.NOT_AIR not in (fields[name].get("depends_on") or "")
        ]
        self.assertEqual(without, [], f"no air rule in project.json: {without}")

    def test_every_air_only_field_depends_on_air(self):
        fields = _project_fields()
        without = [
            name
            for name in afv.AIR_ONLY_PROJECT_FIELDS
            if afv.IS_AIR not in (fields[name].get("depends_on") or "")
        ]
        self.assertEqual(without, [])

    def test_an_existing_rule_was_kept_not_replaced(self):
        dep = _project_fields()["custom_section_container_deposit_refund"]["depends_on"]
        self.assertIn("custom_bill_of_lading", dep)
        self.assertIn(afv.NOT_AIR, dep)

    def test_air_waybill_covers_export_too(self):
        """It used to name Air Import only, so Air Export never showed the field."""
        dep = _project_fields()["custom_air_waybill"]["depends_on"]
        self.assertIn(afv.IS_AIR, dep)
        self.assertNotIn("Air Import", dep)

    def test_the_sea_fields_that_already_had_a_mode_rule_are_untouched(self):
        """Vessel and Bill of Lading were already Sea-only; nothing to add."""
        fields = _project_fields()
        for name in ("custom_vessel", "custom_bill_of_lading"):
            self.assertIn("Sea", fields[name]["depends_on"])
            self.assertNotIn(name, afv.SEA_ONLY_PROJECT_FIELDS)


class TestOpportunityCarriesTheSameRule(unittest.TestCase):
    """An air file starts on Opportunity, so it must not ask sea questions either."""

    def _fields(self):
        data = json.loads(OPPORTUNITY_JSON.read_text())
        return {f["fieldname"]: f for f in data.get("custom_fields", [])}

    def test_every_sea_only_field_depends_on_not_air(self):
        fields = self._fields()
        without = [
            n
            for n in afv.SEA_ONLY_OPPORTUNITY_FIELDS
            if afv.NOT_AIR not in (fields[n].get("depends_on") or "")
        ]
        self.assertEqual(without, [], f"no air rule in opportunity.json: {without}")

    def test_every_air_only_field_depends_on_air(self):
        fields = self._fields()
        without = [
            n
            for n in afv.AIR_ONLY_OPPORTUNITY_FIELDS
            if afv.IS_AIR not in (fields[n].get("depends_on") or "")
        ]
        self.assertEqual(without, [])

    def test_the_intake_stage_rule_was_kept(self):
        """Combined with the air clause, not replaced by it."""
        dep = self._fields()["custom_shipping_line"]["depends_on"]
        self.assertIn("custom_intake_stage", dep)
        self.assertIn(afv.NOT_AIR, dep)

    def test_routing_ports_stay_on_air(self):
        """On an air waybill these are the airports, so air needs them."""
        fields = self._fields()
        for n in ("custom_port_of_loading", "custom_port_of_discharge"):
            self.assertNotIn(afv.NOT_AIR, fields[n].get("depends_on") or "")
            self.assertNotIn(n, afv.SEA_ONLY_OPPORTUNITY_FIELDS)

    def test_the_airline_carries_across_to_the_project(self):
        """Air has no flight field, so Airline is the one that must arrive."""
        from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment import (
            opportunity_to_project_field_pairs,
        )

        self.assertIn(("custom_airline", "custom_airline"), opportunity_to_project_field_pairs())

    def test_neither_form_grew_a_flight_field(self):
        proj = {f["fieldname"] for f in json.loads(PROJECT_JSON.read_text())["custom_fields"]}
        self.assertNotIn("custom_flight_number", proj)
        self.assertNotIn("custom_flight_number", self._fields())


class TestWhatCountsAsAir(unittest.TestCase):
    def test_mode_air(self):
        self.assertTrue(afv.project_is_air(frappe._dict({"custom_mode_of_transport": "Air"})))

    def test_shipment_type_air_without_the_mode(self):
        self.assertTrue(afv.project_is_air(frappe._dict({"custom_shipment_type": "Air Import"})))

    def test_sea_is_not_air(self):
        doc = frappe._dict({"custom_mode_of_transport": "Sea", "custom_shipment_type": "Sea Import"})
        self.assertFalse(afv.project_is_air(doc))

    def test_road_is_not_air(self):
        self.assertFalse(afv.project_is_air(frappe._dict({"custom_mode_of_transport": "Road"})))

    def test_blank_is_not_air(self):
        self.assertFalse(afv.project_is_air(frappe._dict({})))


class _Doc(frappe._dict):
    """Project stand-in: every field exists and set() records the write."""

    @property
    def meta(self):
        return frappe._dict({"has_field": lambda _f: True})

    def set(self, key, value):
        self[key] = value


class TestClearingStampedDefaults(unittest.TestCase):
    def test_an_untouched_berth_phase_goes(self):
        doc = _Doc({"custom_mode_of_transport": "Air", "custom_berth_phase": "Before Vessel Berth"})
        afv.clear_sea_only_fields_on_air(doc)
        self.assertIsNone(doc["custom_berth_phase"])

    def test_a_chosen_berth_phase_stays(self):
        doc = _Doc({"custom_mode_of_transport": "Air", "custom_berth_phase": "After Vessel Berthed"})
        afv.clear_sea_only_fields_on_air(doc)
        self.assertEqual(doc["custom_berth_phase"], "After Vessel Berthed")

    def test_tracker_mode_is_hidden_but_kept(self):
        """The Shipment Type backfill would restore it, so clearing it is pointless."""
        doc = _Doc({"custom_mode_of_transport": "Air", "custom_container_tracker_mode": "ICD Nairobi"})
        afv.clear_sea_only_fields_on_air(doc)
        self.assertEqual(doc["custom_container_tracker_mode"], "ICD Nairobi")
        self.assertIn("custom_container_tracker_mode", afv.SEA_ONLY_PROJECT_FIELDS)

    def test_a_sea_project_is_untouched(self):
        doc = _Doc({"custom_mode_of_transport": "Sea", "custom_berth_phase": "Before Vessel Berth"})
        afv.clear_sea_only_fields_on_air(doc)
        self.assertEqual(doc["custom_berth_phase"], "Before Vessel Berth")

    def test_a_station_somebody_typed_is_kept(self):
        """Hidden on air, never deleted: JKIA was entered by hand."""
        doc = _Doc({"custom_mode_of_transport": "Air", "custom_station_code": "JKIA",
                    "custom_clearance_station": "JKIA"})
        afv.clear_sea_only_fields_on_air(doc)
        self.assertEqual(doc["custom_station_code"], "JKIA")
        self.assertEqual(doc["custom_clearance_station"], "JKIA")


class TestDeclarantRunsTheAirFile(unittest.TestCase):
    AIR = frappe._dict({"custom_task_flow_key": "Air Import Workflow", "department": "Finance - CWSCL"})
    SEA = frappe._dict({"custom_task_flow_key": "Sea Import Workflow", "department": "Finance - CWSCL"})

    def _as_declarant(self, yes):
        from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perms

        return patch.object(perms, "user_has_declarant_department_access", return_value=yes)

    def test_a_declarant_reaches_a_finance_step_of_an_air_file(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perms

        with self._as_declarant(True):
            self.assertTrue(perms.declarant_runs_whole_air_file(self.AIR, "d@x.com"))

    def test_sea_keeps_its_department_split(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perms

        with self._as_declarant(True):
            self.assertFalse(perms.declarant_runs_whole_air_file(self.SEA, "d@x.com"))

    def test_a_non_declarant_gains_nothing(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perms

        with self._as_declarant(False):
            self.assertFalse(perms.declarant_runs_whole_air_file(self.AIR, "f@x.com"))

    def test_the_list_filter_says_the_same_thing(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perms

        with self._as_declarant(True):
            sql = perms.air_file_sql_for_user("d@x.com")
        self.assertIn("Air Import Workflow", sql)
        self.assertIn("Air Export Workflow", sql)
        self.assertIn("custom_task_flow_key", sql)

    def test_the_list_filter_is_empty_for_everyone_else(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perms

        with self._as_declarant(False):
            self.assertEqual(perms.air_file_sql_for_user("f@x.com"), "")

    def _real_conditions(self, user):
        """The whole filter, as the Task list actually builds it."""
        from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perms

        with (
            patch.object(perms, "user_bypasses_sea_task_department_filter", return_value=False),
            patch.object(perms, "visibility_department_stems_for_user", return_value={"Declaration"}),
        ):
            return perms.get_permission_query_conditions(user)

    def test_a_declaration_only_user_gets_the_air_clause(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perms

        with (
            self._as_declarant(True),
            patch.object(perms, "_declaration_only_visibility", return_value=True),
        ):
            sql = self._real_conditions("d@x.com")
        self.assertIn("Air Import Workflow", sql)

    def test_a_hybrid_user_who_is_a_declarant_gets_it_too(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perms

        with (
            self._as_declarant(True),
            patch.object(perms, "_declaration_only_visibility", return_value=False),
            patch.object(perms, "_documentation_only_visibility", return_value=False),
            patch.object(perms, "_operations_only_visibility", return_value=False),
            patch.object(perms, "_transport_only_visibility", return_value=False),
            patch.object(perms, "_field_operations_only_visibility", return_value=False),
            patch.object(perms, "_finance_only_visibility", return_value=False),
        ):
            sql = self._real_conditions("d@x.com")
        self.assertIn("Air Import Workflow", sql)

    def test_a_non_declarant_list_has_no_air_clause(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations import permissions as perms

        with (
            self._as_declarant(False),
            patch.object(perms, "_declaration_only_visibility", return_value=False),
            patch.object(perms, "_documentation_only_visibility", return_value=True),
        ):
            sql = self._real_conditions("doc@x.com")
        self.assertNotIn("Air Import Workflow", sql)


if __name__ == "__main__":
    unittest.main()
