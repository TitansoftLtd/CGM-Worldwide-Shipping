"""A field that belongs to one mode must say so, or be listed here on purpose.

Every complaint behind these rules is the same one: the app was built for sea
import, so a field nobody switched off followed air, export and transit around.
Project, Opportunity, Task and Container Tracker were each fixed after a client
noticed. This test is what stops the fifth one.

Adding a field with a sea word in its name and no mode rule fails here. Either
give it a rule or add it to ALLOWED with the reason.
"""

import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "cgm_worldwide_shipping"

FORMS = {
    "Project": (ROOT / "custom/project.json", "custom_fields"),
    "Opportunity": (ROOT / "custom/opportunity.json", "custom_fields"),
    "Task": (ROOT / "custom/task.json", "custom_fields"),
    "Container Tracker": (ROOT / "doctype/container_tracker/container_tracker.json", "fields"),
}

#: Words that name one mode's world.
SEA_WORDS = (
    "container", "vessel", "voyage", "shipping_line", "berth", "cfs", "cutoff",
    "station", "ecms", "batch", "bill_of_lading", "deposit", "demurrage", "kpa",
    "fcl", "stuffing", "sailing", "coe_", "interchange", "empty_return", "free_days",
)
#: Fieldnames that merely contain a sea word by accident.
NOT_REALLY = ("opportunity", "transport", "support", "report", "important")

#: A field decides the mode, or is read by every mode. Keep the reason with it.
ALLOWED = {
    # The fields the rules are keyed on.
    "Project": {"custom_mode_of_transport", "custom_container_tracker_mode"},
    "Opportunity": {
        "custom_mode_of_transport",
        # On an air waybill these are the airports, so air needs them.
        "custom_port_of_loading",
        "custom_port_of_discharge",
    },
    "Task": {
        # Toggled in task.js by the task's own role, not by mode.
        "custom_container_updates",
        "custom_requires_container_update",
        "custom_section_container_updates",
    },
    "Container Tracker": {
        # Identity, on every container whatever it is doing.
        "container_number",
        "container_mode",
        "shipping_line",
    },
}

MODE_KEYS = ("mode_of_transport", "container_mode", "shipment_type", "cargo_type",
             "task_flow_key", "payment_kind", "task_role")


def _fields(path: pathlib.Path, key: str) -> list[dict]:
    return json.loads(path.read_text()).get(key) or []


def _guarded(field: dict, parents: list[str]) -> bool:
    """A rule on the field, on a section or tab above it, or always hidden."""
    if field.get("hidden"):
        return True
    for rule in [field.get("depends_on") or "", *parents]:
        if any(k in rule for k in MODE_KEYS):
            return True
    return False


def _walk(path: pathlib.Path, key: str):
    """Yield (field, rules of the section and tab it sits under)."""
    data = json.loads(path.read_text())
    fields = {f["fieldname"]: f for f in _fields(path, key)}
    order = data.get("field_order") or list(fields)
    tab = sec = ""
    for name in order:
        f = fields.get(name)
        if not f:
            continue
        ft = f.get("fieldtype")
        if ft == "Tab Break":
            tab, sec = f.get("depends_on") or "", ""
        elif ft == "Section Break":
            sec = f.get("depends_on") or ""
        yield f, [tab, sec]


class TestEveryModeFieldSaysSo(unittest.TestCase):
    def test_no_unguarded_mode_specific_field(self):
        offenders = {}
        for form, (path, key) in FORMS.items():
            bad = [
                f["fieldname"]
                for f, parents in _walk(path, key)
                if f.get("fieldtype") not in ("Column Break",)
                and any(w in f["fieldname"] for w in SEA_WORDS)
                and not any(n in f["fieldname"] for n in NOT_REALLY)
                and f["fieldname"] not in ALLOWED[form]
                and not _guarded(f, parents)
            ]
            if bad:
                offenders[form] = sorted(bad)
        self.assertEqual(
            offenders,
            {},
            "These fields follow every mode around. Give each a depends_on, or add "
            f"it to ALLOWED with the reason: {offenders}",
        )

    def test_the_allowlist_has_no_stale_entries(self):
        """A name left here after the field is gone hides a real gap later."""
        for form, (path, key) in FORMS.items():
            names = {f["fieldname"] for f in _fields(path, key)}
            stale = sorted(ALLOWED[form] - names)
            self.assertEqual(stale, [], f"{form}: allowlist names fields that no longer exist")

    def test_the_charge_and_deposit_rules_match_the_profiles(self):
        """The JSON must say what the code derives, not a copy that drifts.

        Renaming a payment kind fails here, not silently on a live task.
        """
        from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
            charge_field_depends_on,
            deposit_field_depends_on,
        )

        fields = {f["fieldname"]: f for f in _fields(*FORMS["Task"])}
        for name, rule in {**charge_field_depends_on(), **deposit_field_depends_on()}.items():
            self.assertIn(name, fields, f"{name} is derived but not on the form")
            self.assertEqual(
                fields[name].get("depends_on"),
                rule,
                f"{name}: custom/task.json disagrees with task_behaviour",
            )

    def test_every_charge_profile_has_a_rule(self):
        """A charge added later must not land back on every task at once."""
        from cgm_shipping.cgm_worldwide_shipping.customizations.application_finance import (
            APPLICATION_FINANCE_PROFILES,
        )
        from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
            charge_field_depends_on,
        )

        rules = charge_field_depends_on()
        missing = sorted(
            profile.application_submitted_field
            for profile in APPLICATION_FINANCE_PROFILES.values()
            if profile.application_submitted_field
            and profile.application_submitted_field not in rules
        )
        self.assertEqual(missing, [], "these charges would show on every task")


if __name__ == "__main__":
    unittest.main()
