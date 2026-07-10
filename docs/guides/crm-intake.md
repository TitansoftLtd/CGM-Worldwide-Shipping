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

```
Lead
  → attach CI, PKL, B/L, container details
    → Opportunity
      → client documents, workflow approval
        → [Approved] + Customer party
          → Project (sea-import task plan created)
```

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

- **Client documents** (`custom_clients_documents`) — Shipment Document child table
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

- **CI** (Commercial Invoice) — verified on Project shipment documents
- **PKL** (Packing List) — verified on Project shipment documents

These are mandatory intake codes (`INTAKE_DOCUMENT_CODES`).

---

## Bill of Lading

- Unique `bl_number`
- Container child table
- Can link to Opportunity (`custom_linked_opportunity`)
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
- [Admin & Setup](admin-setup.md)
