"""The Opportunity title names the customer, never the container count.

Opportunities appeared on production titled "8 x 20FT" or "10 x 40FT" - the
container summary copied off the Bill of Lading - rather than the company. The
customer link was always correct; only the title was wrong, and two things kept it
that way:

* ERPNext fills the title from the customer **only when it is empty**
  (`if not self.title`), so a single bad value was permanent.
* The field is hidden on the form, so nobody could see it to correct it.

What wrote it was never identified. On production there is no Client Script, no
Server Script, no Property Setter on the field, and the live DocField has no
`options`, `default` or `fetch_from`, so Frappe's template path cannot fire. It was
intermittent too: on 15 October one Opportunity broke while the three created after
it were fine.

The guard therefore does not try to name a cause. It restores the invariant on
every save, after ERPNext has had its turn, so whatever did it is held - while
staying narrow enough that a title somebody typed is never touched.
"""

import unittest

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment import (
    keep_customer_in_opportunity_title,
)


def _doc(**values):
    doc = frappe._dict(values)
    doc.meta = frappe._dict(has_field=lambda f: f in ("custom_quantity", "title", "customer_name", "party_name"))
    return doc


class TestTitleGuard(unittest.TestCase):
    CUSTOMER = "Lionpro Group (k) Limited"

    def test_a_quantity_in_the_title_is_replaced_by_the_customer(self):
        """The reported fault, as it appeared on eight production records."""
        doc = _doc(title="8 x 20FT", custom_quantity="8 x 20FT", customer_name=self.CUSTOMER)
        keep_customer_in_opportunity_title(doc)
        self.assertEqual(doc.title, self.CUSTOMER)

    def test_the_quantity_field_itself_is_left_alone(self):
        """The container summary belongs there; only the title was wrong."""
        doc = _doc(title="8 x 20FT", custom_quantity="8 x 20FT", customer_name=self.CUSTOMER)
        keep_customer_in_opportunity_title(doc)
        self.assertEqual(doc.custom_quantity, "8 x 20FT")

    def test_a_title_somebody_typed_is_never_touched(self):
        doc = _doc(title="Urgent rush job", custom_quantity="8 x 20FT", customer_name=self.CUSTOMER)
        keep_customer_in_opportunity_title(doc)
        self.assertEqual(doc.title, "Urgent rush job")

    def test_a_correct_title_is_left_alone(self):
        doc = _doc(title=self.CUSTOMER, custom_quantity="8 x 20FT", customer_name=self.CUSTOMER)
        keep_customer_in_opportunity_title(doc)
        self.assertEqual(doc.title, self.CUSTOMER)

    def test_it_falls_back_to_party_name(self):
        """customer_name is fetched, so it can still be empty mid-save."""
        doc = _doc(title="2 x 40FT", custom_quantity="2 x 40FT", customer_name="", party_name=self.CUSTOMER)
        keep_customer_in_opportunity_title(doc)
        self.assertEqual(doc.title, self.CUSTOMER)

    def test_with_no_customer_at_all_the_title_is_left_as_is(self):
        """Blanking it would make the row read as its document ID instead."""
        doc = _doc(title="2 x 40FT", custom_quantity="2 x 40FT", customer_name="", party_name="")
        keep_customer_in_opportunity_title(doc)
        self.assertEqual(doc.title, "2 x 40FT")

    def test_an_empty_quantity_is_not_a_match(self):
        doc = _doc(title="", custom_quantity="", customer_name=self.CUSTOMER)
        keep_customer_in_opportunity_title(doc)
        self.assertEqual(doc.title, "")

    def test_surrounding_whitespace_still_matches(self):
        doc = _doc(title="  8 x 20FT ", custom_quantity="8 x 20FT", customer_name=self.CUSTOMER)
        keep_customer_in_opportunity_title(doc)
        self.assertEqual(doc.title, self.CUSTOMER)

    def test_a_site_without_the_quantity_field_is_unaffected(self):
        doc = frappe._dict(title="8 x 20FT", customer_name=self.CUSTOMER)
        doc.meta = frappe._dict(has_field=lambda _f: False)
        keep_customer_in_opportunity_title(doc)
        self.assertEqual(doc.title, "8 x 20FT")


class TestItRunsOnSave(unittest.TestCase):
    def test_the_hook_is_registered_after_erpnexts_own_validate(self):
        """App hooks run after the class method, so this has the last word."""
        hooks = frappe.get_hooks("doc_events", app_name="cgm_shipping") or {}
        validate = (hooks.get("Opportunity") or {}).get("validate") or []
        self.assertTrue(
            any("keep_customer_in_opportunity_title" in h for h in validate),
            f"guard not wired into Opportunity validate: {validate}",
        )
