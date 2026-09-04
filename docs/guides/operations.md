# Operations Guide

For **Operations**, **Documentation**, and **Field Operations** teams managing shipments day-to-day on Desk.

---

## Where to work

| Item | Path in Desk |
|------|----------------|
| Workspace | **CGM Shipping** |
| Shipment record | **Project** (filter by `custom_cgm_ref_no` or customer) |
| Tasks | **Task** (linked to Project; filtered by your department) |
| Live containers | **Container Ops Board** (page) |
| Daily reporting | **Daily Status Update** |

---

## How a shipment moves

A shipment lives as one **Project** from the moment sales hand it over until the containers are back. Four things happen, in this order:

1. **It is created.** Not by hand - an approved Opportunity is started as a shipment, which creates the Project with the cargo, parties and transport details already filled in. See the [CRM & Intake Guide](crm-intake.md).
2. **Its plan is written.** The task engine reads the Shipment Type and writes the whole clearance plan onto it at once (see [below](#where-the-tasks-come-from)).
3. **The plan is worked.** Each team completes its own tasks. As they close, the shipment status advances - but only as far as the completed tasks allow.
4. **It closes.** Every task complete, containers returned, status **Completed**.

The Project form shows all of this in one place. The stepper across the top is the clearance status, the line under it is progress against the plan and the next thing anyone is waiting on:

![A shipment Project: the clearance workflow stepper, task progress and the next open task](../images/project-record.png)

Read it as: **Documents Received** is where the shipment is now, **Draft** is behind it, *2/23 clearance tasks completed*, and the next thing needed is **Task 3: Create UCR (IDF)**. The tabs carry the rest - containers, the customer conversation, and costs.

---

## Your tasks in the sea-import plan (25 steps)

| Seq | Task | Your team |
|-----|------|-----------|
| 1 | Receive shipment documents from Client | Operations |
| 2 | Share documents with Declarants | Operations |
| 7 | Client conducts inspection | Operations |
| 8 | Receive Final Clearance Documents | Documentation |
| 9 | Request Manifest and Local Import Charges | Documentation |
| 12 | Attach Shipping Line Invoice | Documentation |
| 14 | Lodge Delivery Order | Operations |
| 17 | Field Officers conduct clearance | Field Operations |
| 18 | Supervisor obtains KPA Invoice | Operations |

Tasks **1–2** auto-complete when intake documents are verified on the Project.

!!! note "Finance-owned steps"
    Steps 4, 6, 11, 13, 16, 19 are Finance tasks. You attach invoices; Finance pays. See the [Finance Guide](finance.md).

!!! note "Declaration-owned steps"
    UCR, permits, and entry creation are Declaration tasks. See [Declaration & Customs Guide](declaration-customs.md).

!!! note "Transport-owned steps"
    Steps 20–25 are Transport. See [Transport & Containers Guide](transport-containers.md).

### Where the tasks come from

Nobody creates these by hand. The moment a Project is created, the task engine reads the **Shipment Type**, follows it to that type's **CGM Task Template**, and writes the whole plan onto the shipment at once - so a new shipment arrives with its tasks already in place and assigned to the right departments.

| Shipment Type | Template | Tasks created |
|---------------|----------|---------------|
| Sea Import | Sea Import Workflow | 23 |
| Air Import | Air Import Workflow | 16 |
| Sea Transit | Sea Transit Import Workflow | 15 |
| Road Transit Import | Road Transit Inbound Workflow | 11 |

**A Project saved without a Shipment Type gets no tasks at all**, silently - there is nothing in the form to tell you. The same is true of a type with no template behind it (**Import** and **Sea FCL** currently have none). If a shipment has an empty task list, that is the first thing to check.

The whole plan lands on the shipment at once, in sequence, with the first steps already closed where intake documents were verified:

![The task list for one shipment: the generated clearance plan in sequence](../images/project-tasks.png)

Because the plan is written at creation, editing a template changes shipments created **after** the edit. It does not rewrite shipments already running - those keep the plan they were opened with, and setting the Shipment Type later does not backfill them.

---

## Project workflow (shipment status)

The Project field **`custom_shipment_status`** tracks clearance progress (`CGM Sea Import Workflow`):

```
Draft
  → Documents Received
  → UCR Applied → UCR Paid
  → Pre-clearance
  → Client Inspection
  → In Transit
  → Final Docs Received
  → Manifest Requested
  → Entry Lodged → Entry Paid
  → Line Paid & DO Lodged
  → Post-clearance
  → Field Clearance
  → KPA Paid
  → In Delivery
  → Containers Returned
  → Completed
```

### What blocks you from advancing status

| Rule | Meaning |
|------|---------|
| **Task gates** | You cannot skip ahead of incomplete tasks (configured in CGM Shipping Settings) |
| **Document gates** | Required documents must be **Verified** before some state changes |
| **Intake documents** | **CI** and **PKL** required before **Documents Received** |
| **Closure** | All 25 sea tasks must be complete before **Completed** |

---

## Documents on Project

Open the Project → **Shipment Documents** child table.

| Action | When |
|--------|------|
| Upload initial version | Client sends draft document |
| Upload final version | Corrected / stamped version received |
| Verify / Reject | Supervisor confirms document is acceptable |

Document types are masters in **Document Type** (codes like `CI`, `PKL`, `MANIFEST`, `DO`, etc.).

---

## Container Ops Board

Route: **CGM Shipping → Container Ops Board** or `/app/container-ops-board`

Use this page to:

- See overdue empty returns and demurrage risk
- Filter by client, project, B/L, batch, clearance station
- Track containers through lifecycle statuses
- Monitor **Empty Return Tracker** tab

Container statuses: Pending Arrival → Vessel Berthed → Discharged / At Port → Released / In Transit → At Warehouse → Cargo Offloaded → Empty Returned → Interchange Received.

---

## Daily Status Update

Submit a **Daily Status Update** (`DSU-{date}-{#####}`) for RAG reporting on active shipments. Finance and management receive notifications when configured.

---

## Common workflow

### New shipment (after CRM)

1. Confirm Project exists from approved Opportunity.
2. Verify **CI** and **PKL** on Project documents.
3. Advance status to **Documents Received** when intake is complete.
4. Complete task 1–2 (often automatic).
5. Hand off to Declaration for UCR (task 3).

### After vessel arrival

1. Confirm ATA on Project (Actions → Confirm Shipment Arrival at the Port) to create Container Trackers.
2. Create Entry (Declaration, task 12) proceeds independently for Entry Slip / ENTRY paperwork.
3. After finance pays entry (task 13), continue shipping-line / DO steps as sequenced.
4. Lodge DO when line charges are paid.

### Field clearance

1. Complete task 17 (field officers).
2. Obtain KPA invoice (task 18) → Finance pays (task 19).
3. Transport takes over for delivery (tasks 20–25).

---

## Tips & guards

- You only see **Tasks** for your **department** (permission-scoped).
- Do not manually edit **Finance Cost Total** on Project - it is system-calculated.
- One **Project** per **Opportunity**; use `custom_source_opportunity` to trace origin.
- B/L container rows sync to **Container Tracker** records on the Project.

---

## Related guides

- [Declaration & Customs](declaration-customs.md)
- [Finance](finance.md)
- [Transport & Containers](transport-containers.md)
- [CRM & Intake](crm-intake.md)
