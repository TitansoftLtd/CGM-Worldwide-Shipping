"""Replace the legacy SUP_INV document requirement on the sea task plan.

SUP_INV ("Supplier Invoice") is a finance document that the Journal-Entry
migration now strips from Task Documents on save — so any task requiring it
could never be completed. Seq 17 ("Supervisor obtains KPA Invoice") needs a
real, attachable proof, so it moves to a dedicated KPA_INV ("KPA Invoice")
document type. The dormant SUP_INV requirements on the finance-payment steps
(seq 12, 14, 18 — which skip document validation anyway) are dropped.
"""
import frappe

KPA_INV_CODE = "KPA_INV"
SUP_INV_CODE = "SUP_INV"
KEEP_KPA_SEQ = 17  # Supervisor obtains KPA Invoice
SETTINGS_REQUIREMENTS_FIELD = "custom_sea_clearance_task_requirements"


def execute():
    _ensure_kpa_invoice_document_type()
    _repoint_requirements()


def _ensure_kpa_invoice_document_type():
    if frappe.db.exists("Document Type", KPA_INV_CODE):
        return
    doc = frappe.new_doc("Document Type")
    doc.code = KPA_INV_CODE
    doc.category = "Finance"
    doc.required_stage = "Port & line (DO / charges)"
    doc.default_required = 0
    doc.insert(ignore_permissions=True)


def _repoint_requirements():
    if not frappe.db.exists("DocType", "CGM Shipping Settings"):
        return
    settings = frappe.get_single("CGM Shipping Settings")
    rows = settings.get(SETTINGS_REQUIREMENTS_FIELD) or []
    changed = False
    keep = []
    for row in rows:
        is_sup_inv = row.requirement_type == "Document" and (row.value or "").strip() == SUP_INV_CODE
        if is_sup_inv and int(row.sequence_no or 0) == KEEP_KPA_SEQ:
            row.value = KPA_INV_CODE
            changed = True
            keep.append(row)
        elif is_sup_inv:
            # Drop the dormant SUP_INV requirement on the finance-payment steps.
            changed = True
        else:
            keep.append(row)

    if not changed:
        return

    settings.set(SETTINGS_REQUIREMENTS_FIELD, [])
    for row in keep:
        settings.append(SETTINGS_REQUIREMENTS_FIELD, row)
    settings.save(ignore_permissions=True)
