# CRM & Intake Guide

For **sales** and **customer onboarding**: Lead → Opportunity → Project.

---

## Where to work

| Item | Path in Desk |
|------|----------------|
| New enquiry | **Lead** |
| Qualified deal | **Opportunity** |
| Live shipment | **Project** |
| Transport docs | **Bill of Lading**, **Air Waybill** |

---

## The intake flow

Opportunity is the **shipment intake & authorization record** (single source of truth).
Transport documents (Booking Confirmation, Bill of Lading, Air Waybill) synchronize into it.
The Project is created only after approval.

```
New Shipment
  → Create Opportunity → Select Shipment Type
    → Choose initial document (BL / Booking / AWB / None for Transit)
      → Complete document → fields sync to Opportunity
        → Upload & verify remaining client documents
          → Approve Opportunity → Start Shipment → Project + Tasks
```

Booking Confirmation = **planned** shipment. Bill of Lading = **confirmed** cargo.
Either may arrive first; both workflows are supported. Adding a BL later (from Opportunity
or Project) prefills from the Booking and replaces planned vessel/ETA/etc. with confirmed values.

---

## Lead

Capture on **Lead**:

| Field / section | Purpose |
|-----------------|---------|
| Shipment type / mode | Drives downstream workflow |
| CI attachment | Commercial Invoice (intake) |
| PKL attachment | Packing List (intake) |
| Bill of Lading | Sea transport reference |
| Container information | Container list preview |

Preshipment containers sync from B/L when linked.

---

## Opportunity

### Required for Project creation

| Requirement | Detail |
|-------------|--------|
| `workflow_state` | Must be **Approved** |
| `party_name` | Must be a **Customer** (not Lead) |
| One Project | Only one Project per Opportunity |

### Key sections

- **Client documents** (`custom_clients_documents`) - Shipment Document child table
- Transport references: B/L, AWB, container type/qty, vessel, clearance station
- Consignee, batch, CGM ref fields

### On approval

Verified documents are stamped when Opportunity reaches approved state (hooks on save/submit).

---

## Creating the Project

From an approved Opportunity:

1. Use the **Create Project** action (or equivalent dashboard link).
2. Project receives:
   - `custom_source_opportunity`
   - `custom_cgm_ref_no` (LP naming: `{qty}X{size}-{batch}/{seq}`)
   - `custom_shipment_status` = Draft
   - Shipment documents carried from Opportunity
3. If Shipment Type uses sea-import workflow → **25 clearance tasks** are created automatically.

---

## Intake document guard

Before Project can move to **Documents Received**:

- **CI** (Commercial Invoice) - verified on Project shipment documents
- **PKL** (Packing List) - verified on Project shipment documents

These are mandatory intake codes (`INTAKE_DOCUMENT_CODES`).

---

## Bill of Lading

- Unique `bl_number`
- Container child table (FCL): when created from a Booking, rows are auto-generated from
  requested size×qty - user only enters container number and seal
- LCL: packages/package type prefilled; no container table
- Links: `linked_opportunity`, optional `booking_confirmation`
- On submit: syncs shipping/cargo/containers into Opportunity (and Project if already created)
- Container rows feed **Container Tracker** on Project

---

## Customer master

On **Customer**, attach **KRA PIN** file → syncs to document type `KRA_PIN` for clearance.

---

## Opportunity dashboard

Opportunity form shows linked B/L, AWB, containers, and preshipment status (custom dashboard in `shipment.py`).

---

## Related guides

- [Operations](operations.md)
- [Commercial](commercial.md)
