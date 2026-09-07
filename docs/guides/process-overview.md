---
title: Getting Started
metatags:
  description: End-to-end CGM Shipping journey from Lead and Opportunity through Project tasks, finance, billing, and portal — for any shipment type.
---

# Getting Started

**How every CGM shipment moves from enquiry to delivery and billing.**

Use this page when you are new to Desk, or when you need the full journey before diving into a department guide. The same pattern applies to all eight Shipment Types — Sea Import is one mode among eight, not the only path.

A typical scenario: Sales opens an Opportunity, picks **Sea Import**, attaches intake documents, and gets approval. The system creates a Project with the Sea Import task plan. Operations, Declaration, Finance, and Transport work their tasks; status advances as gates clear; Sales quotes and invoices; the customer follows progress on the portal.

To open the workspace, go to:

> Home > CGM Shipping

## 1. Prerequisites

Before running a live shipment:

- User accounts with the right roles (Operations, Declaration, Finance, Documentation, Transport, Sales)
- Masters seeded: **Shipment Type**, **Document Type**, **Permit Type**, clearance stations
- **CGM Shipping Settings** reviewed (workflow gates, funding account, notifications)
- Customer master (and Website User if they need the portal)

:::tip
Task plans for every mode are in [Shipment Modes](shipment-modes.md).
:::

## 2. How to run a shipment end to end

### Step 1 — Intake (CRM)

1. Capture the enquiry on **Lead** (optional) or go straight to **Opportunity**.
2. Select **Shipment Type** first — this chooses the **CGM Task Template** and **Container Tracker Mode**.
3. Attach or link transport docs (B/L, Booking Confirmation, or AWB) as the mode requires.
4. Upload and verify client documents (at least **CI** and **PKL** for intake gates).
5. Submit for approval until Opportunity **`workflow_state` = Approved** and party is a **Customer**.

Details: [CRM & Intake](crm-intake.md).

### Step 2 — Project and task plan

1. From the approved Opportunity, **Create Project** (Start Shipment).
2. Project receives `custom_cgm_ref_no`, documents, and `custom_shipment_status` = Draft.
3. Tasks are created from the Shipment Type’s **CGM Task Template** (for example 25 tasks for Sea Import, 14 for Sea Export).

:::note
Sea Import is **one of eight** modes. Full task tables for every type: [Shipment Modes](shipment-modes.md).
:::

### Step 3 — Work by department

| Team | Typical work |
|------|----------------|
| Operations / Documentation | Intake docs, inspection, manifests, DO, KPA invoice |
| Declaration | UCR, permits, customs entry |
| Finance | Clearance task payments; quotation / SI approval; Funding Requests |
| Transport / Field | Trucks, gate-out, delivery, empty return |
| Sales | Quotation and Sales Invoice |

Each user mainly sees **Tasks** for their department. Complete your step, attach required documents, and let Application ↔ Finance payment pairs run in sequence where the template defines them.

### Step 4 — Advance shipment status

On **Project**, **`custom_shipment_status`** follows the sea-import workflow (and related gates). You cannot skip incomplete task gates or unverified documents. Sea Import detail: [Operations](operations.md).

### Step 5 — Quote and invoice

1. Build a **Quotation** (valuation, customs estimates, local charges).
2. Finance approves (**CGM Quotation Approval**).
3. Share with client when ready; create **Sales Invoice** after maker-checker approval.

Details: [Commercial](commercial.md), [Finance](finance.md).

### Step 6 — Portal (optional)

Customers use `/portal` for progress, documents, quotations, and invoices. Transporters use `/transporter` for allocations. See [Customer & Transporter Portal](portals.md).

## 3. Features — Desk map

| Workspace area | What you open |
|----------------|---------------|
| **Shortcuts** | Customer, Project, B/L, AWB, Opportunity, Container Tracker, Ops Board, Customs Entry |
| **Shipments** | Project, B/L, AWB, Export Shipment, Shipment tracker, Daily Status Update |
| **Clearance & Customs** | Customs Entry, IDF UCR, stations, KPA / shipping-line charges |
| **Transport & Containers** | Container Tracker, Ops Board, seals, interchange, tracking reports |
| **Finance & Funding** | Funding Request, Material Request (via Accounting / Stock) |
| **Masters & Setup** | Shipment Type, Document Type, Permit Type, **CGM Shipping Settings** |
| **Licences & Permits** | Company License Register (not client shipment permits) |
| **Pages** | Container Ops Board (`container-ops-board`), Operations Overview (`operations-overview`) |

## 4. Features — Two finance lanes

| Path | When to use |
|------|-------------|
| **Clearance task payments** | UCR, permits, shipping line, entry slip, KPA on shipment Tasks |
| **Funding Request** | Operational expense or purchase via Material Request batches |

See [Finance](finance.md) and [Funding Request](funding.md).

## 5. Related Topics

- [Shipment Modes](shipment-modes.md) — all eight templates and task lists
- [CRM & Intake](crm-intake.md)
- [Operations](operations.md)
- [Finance](finance.md)
- [Funding Request](funding.md)
- [Customer & Transporter Portal](portals.md)
- [Documentation Hub](../README.md)
