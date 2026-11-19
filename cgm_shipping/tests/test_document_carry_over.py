"""A document reaches the shipment whenever it is attached, not only at creation.

Documents copied from Opportunity to Project only at the moment the Project was
made, and a Booking Confirmation's file only at the moment of submit. Anything
attached later stayed where it was: PROJ-0069 was created in September and its
PKL, CI and COA were uploaded in November, still only on the Opportunity.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import project as proj


class _Meta:
    def __init__(self, fields):
        self._fields = set(fields)

    def has_field(self, name):
        return name in self._fields


class _Row(frappe._dict):
    FIELDS = ("document_type", "draft_documents", "attachment", "final_attachment", "status")

    @property
    def meta(self):
        return _Meta(self.FIELDS)

    def set(self, key, value):
        self[key] = value


class _Doc(frappe._dict):
    def __init__(self, table_field, rows, fields):
        super().__init__()
        self._table = table_field
        self[table_field] = [_Row(r) for r in rows]
        self._fields = fields

    @property
    def meta(self):
        return _Meta(self._fields)

    def append(self, field, row):
        r = _Row(row)
        self[field].append(r)
        return r


def _opp(rows):
    return _Doc("custom_clients_documents", rows, ("custom_clients_documents",))


def _project(rows):
    return _Doc("custom_shipment_documents", rows, ("custom_shipment_documents",))


def _carry(project, opp):
    with patch.object(frappe.db, "exists", return_value=True):
        return proj.carry_new_opportunity_documents_to_project(project, opp)


class TestDocumentsAddedLaterReachTheProject(unittest.TestCase):
    def test_a_document_the_project_lacks_is_added(self):
        p = _project([{"document_type": "BL", "draft_documents": "/bl.pdf"}])
        o = _opp([{"document_type": "BL", "draft_documents": "/bl.pdf"},
                  {"document_type": "PKL", "draft_documents": "/pkl.pdf"}])
        self.assertTrue(_carry(p, o))
        got = {r["document_type"]: r.get("draft_documents") for r in p["custom_shipment_documents"]}
        self.assertEqual(got, {"BL": "/bl.pdf", "PKL": "/pkl.pdf"})

    def test_a_file_already_on_the_project_is_never_replaced(self):
        """The project is the live record during clearance."""
        p = _project([{"document_type": "BL", "draft_documents": "/project-version.pdf"}])
        o = _opp([{"document_type": "BL", "draft_documents": "/older-opportunity.pdf"}])
        self.assertFalse(_carry(p, o))
        self.assertEqual(p["custom_shipment_documents"][0]["draft_documents"], "/project-version.pdf")

    def test_a_final_uploaded_on_the_project_survives(self):
        p = _project([{"document_type": "BL", "draft_documents": "/d.pdf",
                       "final_attachment": "/signed-final.pdf"}])
        o = _opp([{"document_type": "BL", "draft_documents": "/d.pdf",
                   "final_attachment": "/opportunity-final.pdf"}])
        _carry(p, o)
        self.assertEqual(p["custom_shipment_documents"][0]["final_attachment"], "/signed-final.pdf")

    def test_an_empty_slot_on_the_project_is_filled(self):
        p = _project([{"document_type": "BL", "draft_documents": "/d.pdf"}])
        o = _opp([{"document_type": "BL", "draft_documents": "/d.pdf",
                   "final_attachment": "/final.pdf"}])
        self.assertTrue(_carry(p, o))
        self.assertEqual(p["custom_shipment_documents"][0]["final_attachment"], "/final.pdf")

    def test_an_empty_opportunity_row_is_ignored(self):
        p = _project([])
        o = _opp([{"document_type": "Booking", "draft_documents": None, "attachment": ""}])
        self.assertFalse(_carry(p, o))
        self.assertEqual(p["custom_shipment_documents"], [])

    def test_a_row_with_no_document_type_is_ignored(self):
        p = _project([])
        o = _opp([{"document_type": None, "draft_documents": "/x.pdf"}])
        self.assertFalse(_carry(p, o))

    def test_running_it_twice_changes_nothing_the_second_time(self):
        p = _project([])
        o = _opp([{"document_type": "PKL", "draft_documents": "/pkl.pdf"}])
        self.assertTrue(_carry(p, o))
        self.assertFalse(_carry(p, o))

    def test_the_legacy_attachment_field_is_used_when_there_is_no_draft(self):
        p = _project([])
        o = _opp([{"document_type": "CI", "attachment": "/ci.pdf"}])
        self.assertTrue(_carry(p, o))
        self.assertEqual(p["custom_shipment_documents"][0]["draft_documents"], "/ci.pdf")


class TestTheOpportunityHookCarriesDocuments(unittest.TestCase):
    def test_the_sync_calls_the_carry(self):
        """Without this the hook copies scalars and cargo only, as it used to."""
        import inspect

        src = inspect.getsource(proj.sync_linked_project_from_opportunity)
        self.assertIn("carry_new_opportunity_documents_to_project", src)


class TestTheNameFollowsTheQuantity(unittest.TestCase):
    """PROJ-0069 read 0X0 while its quantity read 5 x 40FT."""

    def test_the_opportunity_sync_rebuilds_the_name(self):
        import inspect

        src = inspect.getsource(proj.sync_linked_project_from_opportunity)
        self.assertIn("refresh_project_reference_from_fields", src)

    def test_the_rebuild_happens_before_the_save(self):
        """ignore_validate skips before_save, so the order matters."""
        import inspect

        src = inspect.getsource(proj.sync_linked_project_from_opportunity)
        self.assertLess(
            src.index("refresh_project_reference_from_fields(project)"),
            src.index("project.flags.ignore_validate"),
        )

    def test_a_container_quantity_becomes_the_segment(self):
        from cgm_shipping.cgm_worldwide_shipping.customizations.project_naming import (
            _container_qty_size_from_quantity_field,
        )

        doc = frappe._dict({"custom_quantity": "5 x 40FT"})
        self.assertEqual(_container_qty_size_from_quantity_field(doc), "5X40")


class TestTheBookingFileIsNotOneShot(unittest.TestCase):
    def test_a_submitted_booking_resyncs_on_later_save(self):
        from cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation import (
            booking_confirmation as bc,
        )

        self.assertTrue(hasattr(bc.BookingConfirmation, "on_update_after_submit"))

    def test_a_draft_booking_is_not_carried(self):
        from cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation import (
            booking_confirmation as bc,
        )

        doc = frappe._dict({"attach_booking": "/pi.pdf", "docstatus": 0,
                            "linked_opportunity": "OPP-1"})
        self.assertIsNone(bc.fill_booking_document_from_booking(doc))

    def test_a_booking_with_no_file_is_not_carried(self):
        from cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation import (
            booking_confirmation as bc,
        )

        doc = frappe._dict({"attach_booking": "", "docstatus": 1,
                            "linked_opportunity": "OPP-1"})
        self.assertIsNone(bc.fill_booking_document_from_booking(doc))

    def test_an_unlinked_booking_is_not_carried(self):
        from cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation import (
            booking_confirmation as bc,
        )

        doc = frappe._dict({"attach_booking": "/pi.pdf", "docstatus": 1,
                            "linked_opportunity": None})
        self.assertIsNone(bc.fill_booking_document_from_booking(doc))

    def test_a_failed_carry_does_not_block_saving_the_booking(self):
        """The copy is a convenience; it must not fail someone's edit."""
        from cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation import (
            booking_confirmation as bc,
        )

        booking = bc.BookingConfirmation.__new__(bc.BookingConfirmation)
        booking.name = "SI-TEST"
        with (
            patch.object(bc, "fill_booking_document_from_booking",
                         side_effect=Exception("opportunity would not save")),
            patch.object(bc.frappe, "log_error") as logged,
        ):
            booking.on_update_after_submit()
        logged.assert_called_once()


if __name__ == "__main__":
    unittest.main()
