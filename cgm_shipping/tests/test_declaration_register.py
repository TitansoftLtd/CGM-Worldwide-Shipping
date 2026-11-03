"""A UCR or Entry reads as one line: invoice, document, receipt.

The three papers sat in two tables, and the document row is often absent rather
than empty, so a gap looked the same as a flow that was never set up. Measured on
real data: of 111 declarant UCR/Entry tasks only 16 had all three attached.
"""

import unittest
from unittest.mock import patch

import frappe

from cgm_shipping.cgm_worldwide_shipping.customizations import application_finance as af
from cgm_shipping.cgm_worldwide_shipping.customizations import declaration_register as dr

UCR = af.APPLICATION_FINANCE_PROFILES["UCR Application"]
ENTRY = af.APPLICATION_FINANCE_PROFILES["Entry Application"]
KPA = af.APPLICATION_FINANCE_PROFILES["KPA Application"]


class _Task:
    def __init__(self, finance=None, documents=None, role="Application"):
        self._data = {
            dr.TASK_FINANCE_FIELD: [frappe._dict(r) for r in (finance or [])],
            dr.TASK_DOCUMENTS_FIELD: [frappe._dict(r) for r in (documents or [])],
            "custom_task_role": role,
        }

    def get(self, field, default=None):
        return self._data.get(field, default)


def _register(task, profile=UCR, codes=None):
    """codes maps a Document Type name to its code, as the DB would."""
    codes = codes or {}
    with (
        patch.object(af, "profile_for_task", return_value=profile),
        patch.object(frappe.db, "get_value", side_effect=lambda dt, name, f: codes.get(name)),
    ):
        return dr.declaration_register(task)


def _lines(invoice=None, receipt=None, profile=UCR):
    out = []
    if invoice is not None:
        out.append({"line_label": profile.invoice_label, "attachment": invoice, "verified": 1})
    if receipt is not None:
        out.append({"line_label": profile.receipt_label, "attachment": receipt, "verified": 0})
    return out


class TestTheThreeSlots(unittest.TestCase):
    def test_everything_attached_leaves_nothing_missing(self):
        task = _Task(
            finance=_lines("/files/inv.pdf", "/files/rcpt.pdf"),
            documents=[{"document_type": "IDF CERT", "attachment": "/files/idf.pdf"}],
        )
        reg = _register(task, codes={"IDF CERT": "IDF_CERT"})
        self.assertEqual(reg["missing"], [])
        self.assertEqual(reg["rows"][0]["invoice"]["file_name"], "inv.pdf")

    def test_an_absent_document_row_reads_as_missing(self):
        """This is the bug: no row at all used to look like nothing was wrong."""
        task = _Task(finance=_lines("/files/inv.pdf", "/files/rcpt.pdf"), documents=[])
        self.assertEqual(_register(task)["missing"], ["Document"])

    def test_a_document_row_with_no_file_reads_as_missing(self):
        task = _Task(
            finance=_lines("/files/inv.pdf", "/files/rcpt.pdf"),
            documents=[{"document_type": "IDF CERT", "attachment": ""}],
        )
        self.assertEqual(_register(task, codes={"IDF CERT": "IDF_CERT"})["missing"], ["Document"])

    def test_a_missing_receipt_is_named(self):
        task = _Task(finance=_lines("/files/inv.pdf", ""))
        self.assertIn("Receipt", _register(task)["missing"])

    def test_an_absent_invoice_line_is_named(self):
        task = _Task(finance=_lines(None, "/files/rcpt.pdf"))
        self.assertIn("Invoice", _register(task)["missing"])

    def test_finance_verification_shows_on_the_slot(self):
        task = _Task(finance=_lines("/files/inv.pdf", "/files/rcpt.pdf"))
        row = _register(task)["rows"][0]
        self.assertEqual(row["invoice"]["verified"], 1)
        self.assertEqual(row["receipt"]["verified"], 0)


class TestTheDocumentCodeFamily(unittest.TestCase):
    """A UCR certificate lands under IDF, IDF CERT or UCR_CERT depending on its age."""

    def test_a_plain_idf_row_counts_as_the_ucr_document(self):
        task = _Task(
            finance=_lines("/files/inv.pdf", "/files/rcpt.pdf"),
            documents=[{"document_type": "IDF", "attachment": "/files/idf.pdf"}],
        )
        self.assertEqual(_register(task, codes={"IDF": "IDF"})["missing"], [])

    def test_an_unrelated_document_does_not_count(self):
        task = _Task(
            finance=_lines("/files/inv.pdf", "/files/rcpt.pdf"),
            documents=[{"document_type": "Bill of Lading", "attachment": "/files/bl.pdf"}],
        )
        self.assertEqual(_register(task, codes={"Bill of Lading": "BL"})["missing"], ["Document"])

    def test_entry_takes_only_its_own_code(self):
        task = _Task(
            finance=_lines("/files/inv.pdf", "/files/rcpt.pdf", profile=ENTRY),
            documents=[{"document_type": "IDF", "attachment": "/files/idf.pdf"}],
        )
        reg = _register(task, profile=ENTRY, codes={"IDF": "IDF"})
        self.assertEqual(reg["missing"], ["Document"])

    def test_the_entry_document_counts(self):
        task = _Task(
            finance=_lines("/files/inv.pdf", "/files/rcpt.pdf", profile=ENTRY),
            documents=[{"document_type": "Entry", "attachment": "/files/entry.pdf"}],
        )
        self.assertEqual(_register(task, profile=ENTRY, codes={"Entry": "ENTRY"})["missing"], [])


class TestWhereItShows(unittest.TestCase):
    def test_not_on_the_finance_task(self):
        """Finance never holds the document, so a blank cell there would be a lie."""
        task = _Task(finance=_lines("/files/inv.pdf", "/files/rcpt.pdf"), role="Finance Payment")
        self.assertEqual(_register(task)["rows"], [])

    def test_not_on_a_declaration_with_no_document_of_its_own(self):
        """KPA and CFS keep both their papers in one table already."""
        task = _Task(finance=_lines("/files/inv.pdf", "/files/rcpt.pdf", profile=KPA))
        self.assertEqual(_register(task, profile=KPA)["rows"], [])

    def test_a_task_with_no_profile_gets_nothing(self):
        self.assertEqual(_register(_Task(), profile=None)["rows"], [])


class TestTheLabel(unittest.TestCase):
    def test_the_declaration_is_named_without_the_word_invoice(self):
        task = _Task(finance=_lines("/files/inv.pdf", "/files/rcpt.pdf"))
        self.assertEqual(_register(task)["rows"][0]["label"], "UCR")

    def test_entry_slip_is_named_from_its_invoice_label(self):
        task = _Task(finance=_lines("/files/i.pdf", "/files/r.pdf", profile=ENTRY))
        self.assertEqual(_register(task, profile=ENTRY)["rows"][0]["label"], "Entry Slip")


class TestAmendments(unittest.TestCase):
    def test_a_second_invoice_gets_its_own_line(self):
        finance = _lines("/files/inv.pdf", "/files/rcpt.pdf")
        finance.append(
            {"line_label": UCR.invoice_label, "attachment": "/files/inv2.pdf", "is_amendment": 1}
        )
        reg = _register(_Task(finance=finance))
        self.assertEqual(len(reg["rows"]), 2)
        self.assertTrue(reg["rows"][1]["amendment"])

    def test_the_document_belongs_to_the_declaration_not_the_amendment(self):
        finance = _lines("/files/inv.pdf", "/files/rcpt.pdf")
        finance.append(
            {"line_label": UCR.invoice_label, "attachment": "/files/inv2.pdf", "is_amendment": 1}
        )
        task = _Task(
            finance=finance,
            documents=[{"document_type": "IDF CERT", "attachment": "/files/idf.pdf"}],
        )
        reg = _register(task, codes={"IDF CERT": "IDF_CERT"})
        self.assertEqual(reg["rows"][0]["document"]["state"], "attached")
        self.assertEqual(reg["rows"][1]["document"]["state"], dr.STATE_NOT_APPLICABLE)

    def test_an_amendment_does_not_report_the_document_as_missing(self):
        """It has no document of its own, so counting it as a gap was wrong."""
        finance = _lines("/files/inv.pdf", "/files/rcpt.pdf")
        finance.append(
            {"line_label": UCR.invoice_label, "attachment": "/files/inv2.pdf", "is_amendment": 1}
        )
        task = _Task(
            finance=finance,
            documents=[{"document_type": "IDF CERT", "attachment": "/files/idf.pdf"}],
        )
        reg = _register(task, codes={"IDF CERT": "IDF_CERT"})
        self.assertNotIn("Document", reg["missing"])
        self.assertIn("Receipt", reg["missing"])
