#!/usr/bin/env python3
"""Generate CGM Worldwide Shipping doctype JSON files per erpnext_shipment_guide.html."""
from __future__ import annotations

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "cgm_shipping" / "cgm_worldwide_shipping" / "doctype"
MODULE = "CGM Worldwide Shipping"


def write_doctype(folder: str, data: dict) -> None:
    path = APP / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / "__init__.py").touch()
    name = data["name"]
    py_name = folder
    (path / f"{py_name}.py").write_text(
        f'''# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class {name.replace(" ", "")}(Document):
\tpass
''',
        encoding="utf-8",
    )
    (path / f"{py_name}.json").write_text(
        json.dumps(data, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def std_perms():
    return [
        {
            "role": "System Manager",
            "read": 1,
            "write": 1,
            "create": 1,
            "delete": 1,
            "export": 1,
            "print": 1,
            "email": 1,
            "share": 1,
            "submit": 1,
        }
    ]


# --- CFS Master ---
write_doctype(
    "cfs_master",
    {
        "actions": [],
        "allow_rename": 1,
        "autoname": "field:cfs_name",
        "creation": "2026-05-19 00:00:00.000000",
        "doctype": "DocType",
        "engine": "InnoDB",
        "field_order": ["cfs_name", "cfs_code", "supplier"],
        "fields": [
            {"fieldname": "cfs_name", "fieldtype": "Data", "label": "CFS Name", "reqd": 1, "unique": 1},
            {
                "fieldname": "cfs_code",
                "fieldtype": "Select",
                "label": "CFS Code",
                "options": "MAT\nCSC\nSIG\nTCC\nKAH\nBFT\nICD\nICD-UG",
            },
            {"fieldname": "supplier", "fieldtype": "Link", "label": "Supplier", "options": "Supplier"},
        ],
        "index_web_pages_for_search": 1,
        "links": [],
        "modified": "2026-05-19 00:00:00.000000",
        "modified_by": "Administrator",
        "module": MODULE,
        "name": "CFS Master",
        "owner": "Administrator",
        "permissions": std_perms(),
        "sort_field": "modified",
        "sort_order": "DESC",
        "states": [],
        "track_changes": 1,
    },
)

# --- Permit Register (child) ---
write_doctype(
    "permit_register",
    {
        "actions": [],
        "creation": "2026-05-19 00:00:00.000000",
        "doctype": "DocType",
        "editable_grid": 1,
        "engine": "InnoDB",
        "field_order": [
            "permit_type",
            "stage",
            "application_date",
            "approval_date",
            "issuing_body",
            "invoice_amount",
            "payment_date",
            "payment_reference",
            "status",
            "permit_document",
        ],
        "fields": [
            {
                "fieldname": "permit_type",
                "fieldtype": "Select",
                "label": "Permit Type",
                "options": "DVS\nNBA\nVMD\nACA\nKEBS\nKRPB\nPort Health\nOther",
                "in_list_view": 1,
            },
            {
                "fieldname": "stage",
                "fieldtype": "Select",
                "label": "Stage",
                "options": "Pre-clearance\nPost-clearance",
                "in_list_view": 1,
            },
            {"fieldname": "application_date", "fieldtype": "Date", "label": "Application Date"},
            {"fieldname": "approval_date", "fieldtype": "Date", "label": "Approval Date"},
            {"fieldname": "issuing_body", "fieldtype": "Data", "label": "Issuing Body"},
            {"fieldname": "invoice_amount", "fieldtype": "Currency", "label": "Invoice Amount"},
            {"fieldname": "payment_date", "fieldtype": "Date", "label": "Payment Date"},
            {"fieldname": "payment_reference", "fieldtype": "Data", "label": "Payment Reference"},
            {
                "fieldname": "status",
                "fieldtype": "Select",
                "label": "Status",
                "options": "Applied\nApproved\nPaid\nReleased\nRejected",
                "in_list_view": 1,
            },
            {"fieldname": "permit_document", "fieldtype": "Attach", "label": "Permit Document"},
        ],
        "index_web_pages_for_search": 1,
        "istable": 1,
        "links": [],
        "modified": "2026-05-19 00:00:00.000000",
        "modified_by": "Administrator",
        "module": MODULE,
        "name": "Permit Register",
        "owner": "Administrator",
        "permissions": [],
        "sort_field": "modified",
        "sort_order": "DESC",
        "states": [],
    },
)

# --- Shipment Dossier (master) ---
SHIPMENT_STATUS = (
    "Draft\nDocuments Received\nIDF Open\nPre-clearance\nIn Transit\n"
    "Entry Lodged\nTaxes Paid\nClearance\nReleased\nSettled"
)
write_doctype(
    "shipment_dossier",
    {
        "actions": [],
        "allow_import": 1,
        "allow_rename": 1,
        "autoname": "naming_series:",
        "creation": "2026-05-19 00:00:00.000000",
        "doctype": "DocType",
        "engine": "InnoDB",
        "field_order": [
            "naming_series",
            "shipment_type",
            "status",
            "column_break_hdr1",
            "client",
            "client_reference",
            "consignee",
            "section_break_transport",
            "awb_bl_number",
            "entry_no",
            "cfs",
            "cfs_code",
            "column_break_transport2",
            "weight_nw",
            "weight_gw",
            "eta",
            "ata",
            "vessel_flight",
            "shipping_line",
            "section_break_ops",
            "agent_allocated",
            "date_settled",
            "column_break_charges",
            "handling_charges",
            "breakbulk_charges",
            "kebs_charges",
            "charge_notes",
            "section_break_desc",
            "description",
            "remarks",
            "section_break_permits",
            "permits",
            "section_break_links",
            "project",
        ],
        "fields": [
            {
                "fieldname": "naming_series",
                "fieldtype": "Select",
                "label": "Series",
                "options": "CGM/IM-.YYYY.-.MM.-.###\nCGM/EX-.YYYY.-.MM.-.###\nCGM/LCL-.YYYY.-.MM.-.###\nCGM/FCL-.YYYY.-.MM.-.###",
                "reqd": 1,
            },
            {
                "fieldname": "shipment_type",
                "fieldtype": "Select",
                "label": "Shipment Type",
                "options": "Air Import\nSea FCL\nSea LCL\nRoad Import\nTransit\nExport",
                "reqd": 1,
                "in_list_view": 1,
            },
            {
                "fieldname": "status",
                "fieldtype": "Select",
                "label": "Status",
                "options": SHIPMENT_STATUS,
                "default": "Draft",
                "in_list_view": 1,
                "in_standard_filter": 1,
            },
            {"fieldname": "column_break_hdr1", "fieldtype": "Column Break"},
            {
                "fieldname": "client",
                "fieldtype": "Link",
                "label": "Client",
                "options": "Customer",
                "reqd": 1,
                "in_list_view": 1,
            },
            {"fieldname": "client_reference", "fieldtype": "Data", "label": "Client Reference"},
            {"fieldname": "consignee", "fieldtype": "Data", "label": "Consignee"},
            {"fieldname": "section_break_transport", "fieldtype": "Section Break", "label": "Transport"},
            {"fieldname": "awb_bl_number", "fieldtype": "Data", "label": "AWB / B/L Number"},
            {"fieldname": "entry_no", "fieldtype": "Data", "label": "Entry No"},
            {"fieldname": "cfs", "fieldtype": "Link", "label": "CFS", "options": "CFS Master"},
            {
                "fieldname": "cfs_code",
                "fieldtype": "Select",
                "label": "CFS Code",
                "options": "MAT\nCSC\nSIG\nTCC\nKAH\nBFT\nICD\nICD-UG",
            },
            {"fieldname": "column_break_transport2", "fieldtype": "Column Break"},
            {"fieldname": "weight_nw", "fieldtype": "Float", "label": "Weight (NW) KG"},
            {"fieldname": "weight_gw", "fieldtype": "Float", "label": "Weight (GW) KG"},
            {"fieldname": "eta", "fieldtype": "Date", "label": "ETA"},
            {"fieldname": "ata", "fieldtype": "Date", "label": "ATA"},
            {"fieldname": "vessel_flight", "fieldtype": "Data", "label": "Vessel / Flight"},
            {"fieldname": "shipping_line", "fieldtype": "Link", "label": "Shipping Line", "options": "Supplier"},
            {"fieldname": "section_break_ops", "fieldtype": "Section Break", "label": "Operations"},
            {"fieldname": "agent_allocated", "fieldtype": "Link", "label": "Agent Allocated", "options": "Employee"},
            {"fieldname": "date_settled", "fieldtype": "Date", "label": "Date Settled"},
            {"fieldname": "column_break_charges", "fieldtype": "Column Break", "label": "Charges"},
            {"fieldname": "handling_charges", "fieldtype": "Currency", "label": "Handling Charges"},
            {"fieldname": "breakbulk_charges", "fieldtype": "Currency", "label": "Breakbulk Charges"},
            {"fieldname": "kebs_charges", "fieldtype": "Currency", "label": "KEBS Charges"},
            {"fieldname": "charge_notes", "fieldtype": "Small Text", "label": "Charge Notes"},
            {"fieldname": "section_break_desc", "fieldtype": "Section Break"},
            {"fieldname": "description", "fieldtype": "Small Text", "label": "Description"},
            {"fieldname": "remarks", "fieldtype": "Text", "label": "Remarks"},
            {"fieldname": "section_break_permits", "fieldtype": "Section Break", "label": "Permits"},
            {"fieldname": "permits", "fieldtype": "Table", "label": "Permit Register", "options": "Permit Register"},
            {
                "fieldname": "section_break_links",
                "fieldtype": "Section Break",
                "label": "Legacy / Project Link",
                "collapsible": 1,
            },
            {
                "fieldname": "project",
                "fieldtype": "Link",
                "label": "Linked Project",
                "options": "Project",
                "read_only": 1,
            },
        ],
        "index_web_pages_for_search": 1,
        "is_submittable": 1,
        "links": [],
        "modified": "2026-05-19 00:00:00.000000",
        "modified_by": "Administrator",
        "module": MODULE,
        "name": "Shipment Dossier",
        "naming_rule": "By \"Naming Series\" field",
        "owner": "Administrator",
        "permissions": std_perms(),
        "search_fields": "client,awb_bl_number,entry_no,client_reference",
        "sort_field": "modified",
        "sort_order": "DESC",
        "states": [],
        "track_changes": 1,
    },
)

def link_doc(name: str, folder: str, fields: list, *, submittable=False, extra=None):
    data = {
        "actions": [],
        "allow_rename": 1,
        "creation": "2026-05-19 00:00:00.000000",
        "doctype": "DocType",
        "engine": "InnoDB",
        "field_order": [f["fieldname"] for f in fields],
        "fields": fields,
        "index_web_pages_for_search": 1,
        "is_submittable": 1 if submittable else 0,
        "links": [],
        "modified": "2026-05-19 00:00:00.000000",
        "modified_by": "Administrator",
        "module": MODULE,
        "name": name,
        "owner": "Administrator",
        "permissions": std_perms(),
        "sort_field": "modified",
        "sort_order": "DESC",
        "states": [],
        "track_changes": 1,
    }
    if extra:
        data.update(extra)
    write_doctype(folder, data)


SD = {"fieldname": "shipment_dossier", "fieldtype": "Link", "label": "Shipment Dossier", "options": "Shipment Dossier", "reqd": 1, "in_list_view": 1}

# IDF / UCR Record
link_doc(
    "IDF UCR Record",
    "idf_ucr_record",
    [
        SD,
        {"fieldname": "idf_number", "fieldtype": "Data", "label": "IDF Number"},
        {"fieldname": "ucr_number", "fieldtype": "Data", "label": "UCR Number"},
        {"fieldname": "application_date", "fieldtype": "Date", "label": "Application Date"},
        {"fieldname": "approval_date", "fieldtype": "Date", "label": "Approval Date"},
        {"fieldname": "shared_with_client", "fieldtype": "Check", "label": "Shared With Client"},
        {"fieldname": "ucr_payment_status", "fieldtype": "Select", "label": "UCR Payment Status", "options": "Pending\nPaid"},
        {"fieldname": "payment_reference", "fieldtype": "Data", "label": "Payment Reference"},
        {"fieldname": "remarks", "fieldtype": "Small Text", "label": "Remarks"},
    ],
    submittable=True,
    extra={"autoname": "hash"},
)

# Customs Entry
link_doc(
    "Customs Entry",
    "customs_entry",
    [
        SD,
        {"fieldname": "entry_number", "fieldtype": "Data", "label": "Entry Number", "reqd": 1},
        {"fieldname": "e_slip_reference", "fieldtype": "Data", "label": "E-Slip Reference"},
        {"fieldname": "idf_tax", "fieldtype": "Currency", "label": "IDF Tax"},
        {"fieldname": "vat", "fieldtype": "Currency", "label": "VAT"},
        {"fieldname": "duty", "fieldtype": "Currency", "label": "Duty"},
        {"fieldname": "excise", "fieldtype": "Currency", "label": "Excise"},
        {"fieldname": "payment_status", "fieldtype": "Select", "label": "Payment Status", "options": "Pending\nPaid"},
        {"fieldname": "kra_verification_status", "fieldtype": "Select", "label": "KRA Verification", "options": "Pending\nVerified\nFailed"},
        {"fieldname": "kebs_verification_status", "fieldtype": "Select", "label": "KEBS Verification", "options": "Pending\nVerified\nFailed"},
        {"fieldname": "cro_release_date", "fieldtype": "Date", "label": "CRO Release Date"},
    ],
    submittable=True,
    extra={"autoname": "field:entry_number"},
)

# Container Tracker
link_doc(
    "Container Tracker",
    "container_tracker",
    [
        SD,
        {"fieldname": "container_number", "fieldtype": "Data", "label": "Container Number", "reqd": 1, "in_list_view": 1},
        {"fieldname": "batch_bl_no", "fieldtype": "Data", "label": "Batch / B/L No"},
        {
            "fieldname": "container_mode",
            "fieldtype": "Select",
            "label": "Container Mode",
            "options": "Mombasa Port\nICD Nairobi\nTransit Kenya→Border\nTransit Border→Kenya\nExport",
        },
        {"fieldname": "eta", "fieldtype": "Date", "label": "ETA"},
        {"fieldname": "ata", "fieldtype": "Date", "label": "ATA"},
        {"fieldname": "discharging_date", "fieldtype": "Date", "label": "Discharging Date"},
        {"fieldname": "custom_release_date", "fieldtype": "Date", "label": "Custom Release Date"},
        {"fieldname": "gate_out_date_port", "fieldtype": "Date", "label": "Gate Out Date (Port)"},
        {"fieldname": "truck_number", "fieldtype": "Data", "label": "Truck Number"},
        {"fieldname": "driver_name", "fieldtype": "Data", "label": "Driver Name"},
        {"fieldname": "driver_contact", "fieldtype": "Data", "label": "Driver Contact"},
        {"fieldname": "transporter", "fieldtype": "Link", "label": "Transporter", "options": "Supplier"},
        {"fieldname": "gate_in_date_warehouse", "fieldtype": "Date", "label": "Gate In Date (Warehouse)"},
        {"fieldname": "offloading_date", "fieldtype": "Date", "label": "Offloading Date"},
        {"fieldname": "delivery_date", "fieldtype": "Date", "label": "Delivery Date"},
        {"fieldname": "expected_empty_return", "fieldtype": "Date", "label": "Expected Empty Return", "read_only": 1},
        {"fieldname": "actual_empty_return", "fieldtype": "Date", "label": "Actual Empty Return"},
        {"fieldname": "gate_in_date_depot", "fieldtype": "Date", "label": "Gate In Date (Depot)"},
        {"fieldname": "free_days", "fieldtype": "Int", "label": "Free Days"},
        {"fieldname": "demurrage_days", "fieldtype": "Int", "label": "Demurrage Days", "read_only": 1},
        {"fieldname": "detention_days", "fieldtype": "Int", "label": "Detention Days", "read_only": 1},
        {"fieldname": "daily_demurrage_rate", "fieldtype": "Currency", "label": "Daily Demurrage Rate"},
        {"fieldname": "demurrage_amount", "fieldtype": "Currency", "label": "Demurrage Amount", "read_only": 1},
        {
            "fieldname": "status",
            "fieldtype": "Select",
            "label": "Status",
            "options": "Dispatched\nDelivered\nEmpty Pending\nEmpty Returned\nOverdue",
            "in_list_view": 1,
        },
        {"fieldname": "interchange_date", "fieldtype": "Date", "label": "Interchange Date"},
        {"fieldname": "icd_gate_in_date", "fieldtype": "Date", "label": "ICD Gate In Date"},
        {"fieldname": "icd_gate_out_date", "fieldtype": "Date", "label": "ICD Gate Out Date"},
        {"fieldname": "border_clearance_date", "fieldtype": "Date", "label": "Border Clearance Date"},
    ],
    extra={"autoname": "field:container_number"},
)

# Daily Status Update
link_doc(
    "Daily Status Update",
    "daily_status_update",
    [
        {"fieldname": "date", "fieldtype": "Date", "label": "Date", "default": "Today", "reqd": 1},
        {
            "fieldname": "group_team",
            "fieldtype": "Select",
            "label": "Group / Team",
            "options": "Operations\nDeclarants\nTransport\nFinance\nField",
            "reqd": 1,
        },
        {"fieldname": "submitted_by", "fieldtype": "Link", "label": "Submitted By", "options": "User", "read_only": 1, "default": "__user"},
        {"fieldname": "shipments_dispatched", "fieldtype": "Int", "label": "Shipments Dispatched"},
        {"fieldname": "deliveries_completed", "fieldtype": "Int", "label": "Deliveries Completed"},
        {"fieldname": "delays_issues", "fieldtype": "Text", "label": "Delays / Issues"},
        {"fieldname": "empty_containers_pending", "fieldtype": "Int", "label": "Empty Containers Pending"},
        {"fieldname": "containers_returned_today", "fieldtype": "Int", "label": "Containers Returned Today"},
        {"fieldname": "outstanding_actions", "fieldtype": "Text", "label": "Outstanding Actions"},
        {
            "fieldname": "rag_status",
            "fieldtype": "Select",
            "label": "RAG Status",
            "options": "Green\nYellow\nRed",
            "reqd": 1,
        },
    ],
    submittable=True,
    extra={"autoname": "format:DSU-{date}-{#####}"},
)

# Shipping Line Charges
link_doc(
    "Shipping Line Charges",
    "shipping_line_charges",
    [
        SD,
        {"fieldname": "shipping_line", "fieldtype": "Link", "label": "Shipping Line", "options": "Supplier"},
        {"fieldname": "local_import_charges", "fieldtype": "Currency", "label": "Local Import Charges"},
        {"fieldname": "do_lodgement_date", "fieldtype": "Date", "label": "DO Lodgement Date"},
        {"fieldname": "manifest_receipt_date", "fieldtype": "Date", "label": "Manifest Receipt Date"},
        {
            "fieldname": "cfs_code",
            "fieldtype": "Select",
            "label": "CFS Code",
            "options": "MAT\nCSC\nSIG\nTCC\nKAH\nBFT",
        },
        {"fieldname": "payment_reference", "fieldtype": "Data", "label": "Payment Reference"},
        {"fieldname": "indemnity_form_status", "fieldtype": "Select", "label": "Indemnity Form", "options": "Pending\nReceived\nSubmitted"},
    ],
    submittable=True,
    extra={"autoname": "hash"},
)

# Port Charges KPA Invoice
link_doc(
    "Port Charges KPA Invoice",
    "port_charges_kpa_invoice",
    [
        SD,
        {"fieldname": "kpa_invoice_number", "fieldtype": "Data", "label": "KPA Invoice Number"},
        {"fieldname": "kpa_invoice_amount", "fieldtype": "Currency", "label": "KPA Invoice Amount"},
        {"fieldname": "payment_date", "fieldtype": "Date", "label": "Payment Date"},
        {"fieldname": "pickup_order_date", "fieldtype": "Date", "label": "Pick-up Order Date"},
        {"fieldname": "gate_pass_issued", "fieldtype": "Check", "label": "Gate Pass Issued"},
        {"fieldname": "port_compliance_status", "fieldtype": "Select", "label": "Port Compliance", "options": "Pending\nCompliant\nIssue"},
        {"fieldname": "demurrage_billing_amount", "fieldtype": "Currency", "label": "Demurrage Billing Amount"},
    ],
    submittable=True,
    extra={"autoname": "hash"},
)

# Seal Record
link_doc(
    "Seal Record",
    "seal_record",
    [
        SD,
        {"fieldname": "seal_number", "fieldtype": "Data", "label": "Seal Number", "reqd": 1},
        {
            "fieldname": "seal_point",
            "fieldtype": "Select",
            "label": "Seal Point",
            "options": "Mombasa\nNairobi\nMalaba",
        },
        {"fieldname": "shipment_quantity", "fieldtype": "Float", "label": "Shipment Quantity"},
        {"fieldname": "container_tracker", "fieldtype": "Link", "label": "Container", "options": "Container Tracker"},
        {"fieldname": "date_applied", "fieldtype": "Date", "label": "Date Applied"},
        {"fieldname": "date_removed", "fieldtype": "Date", "label": "Date Removed"},
    ],
    extra={"autoname": "field:seal_number"},
)

# Export Shipment
link_doc(
    "Export Shipment",
    "export_shipment",
    [
        SD,
        {"fieldname": "coc_eac_application_date", "fieldtype": "Date", "label": "COC/EAC Application Date"},
        {"fieldname": "uganda_entry_number", "fieldtype": "Data", "label": "Uganda Entry Number"},
        {"fieldname": "c2_document", "fieldtype": "Attach", "label": "C2 Document"},
        {"fieldname": "exit_note", "fieldtype": "Data", "label": "Exit Note"},
        {"fieldname": "border_clearance_date", "fieldtype": "Date", "label": "Border Clearance Date"},
        {"fieldname": "ecmd_device_number", "fieldtype": "Data", "label": "ECMD Device Number"},
        {"fieldname": "loading_warehouse", "fieldtype": "Data", "label": "Loading Warehouse"},
        {"fieldname": "delivery_warehouse", "fieldtype": "Data", "label": "Delivery Warehouse"},
    ],
    submittable=True,
    extra={"autoname": "hash"},
)

# Interchange Receipt
link_doc(
    "Interchange Receipt",
    "interchange_receipt",
    [
        SD,
        {"fieldname": "container_tracker", "fieldtype": "Link", "label": "Container Tracker", "options": "Container Tracker", "reqd": 1},
        {"fieldname": "depot_name", "fieldtype": "Data", "label": "Depot Name"},
        {"fieldname": "date_returned", "fieldtype": "Date", "label": "Date Returned"},
        {"fieldname": "interchange_document_number", "fieldtype": "Data", "label": "Interchange Document Number"},
        {"fieldname": "deposit_refund_status", "fieldtype": "Select", "label": "Deposit Refund Status", "options": "Pending\nRefunded\nNot Applicable"},
    ],
    submittable=True,
    extra={"autoname": "hash"},
)

print("Bootstrap wrote all doctypes to", APP)
