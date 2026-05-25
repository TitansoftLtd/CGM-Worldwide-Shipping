# End-to-End Import Operations Process Flow (Final)

This is the **authoritative business process** for CGM Worldwide Shipping.  
Implementation mapping: see [Implementation status](#implementation-status) at the end.

---

## 1. Lead Creation (New Customer Process)

A **Lead** is created when a new client engages the company.

**Required documents:**

- Commercial Invoice
- Packing List

These are uploaded at **Lead** level for validation and approval.

Once verified, the Lead is approved and converted into a **Customer**.

**In system:** `CGM Lead Pre-Shipment` workflow on Lead; CI/PKL on Lead; convert to Customer.

---

## 2. Customer Creation

After approval:

A **Customer** record is created.

**Mandatory document:**

- KRA PIN Certificate (stored at Customer level for compliance and reuse on all Projects)

**In system:** Customer custom attachment fields; synced to Project `custom_shipment_documents` on project create/update.

---

## 3. Existing Customer Flow

For returning customers:

- An **Opportunity** is created (not a new Lead)
- Commercial Invoice and Packing List are attached at **Opportunity** level
- Once approved, a **Project** is created

**In system:** `CGM Opportunity Pre-Shipment` workflow; `create_project_from_opportunity` carries CI/PKL to Project.

---

## Project creation and task workflow

### Automatic completion of initial documentation tasks

The first two tasks in the sea task plan are **automatically marked Completed** when a **Sea** Project is created from an approved Lead/Opportunity (CI and PKL already on the Project):

| Task | Subject | Why auto-completed |
|------|---------|-------------------|
| 1 | Receive shipment documents from Client | CI/PKL uploaded and approved on Lead/Opportunity |
| 2 | Share documents with Declarants | Declarations team already reviewed before Project creation |

A Project cannot be created until required pre-shipment documents are approved. Approved CI, PKL, and Customer attachments (e.g. KRA PIN) are carried into the Project. Re-doing these steps as manual tasks adds no value.

**First actionable task** for users is typically **Task 3 — Create UCR (IDF)** (then Finance Task 4, permits, etc.).

### Updated workflow logic

1. Lead/Opportunity created.  
2. Commercial Invoice and Packing List uploaded.  
3. Documentation/Declarations reviews and approves.  
4. Customer created (new) with KRA PIN.  
5. **Project created** — documents populate the Project.  
6. **Sea task plan** created (Sea + CI/PKL on file).  
7. **Task 1** → auto **Completed**.  
8. **Task 2** → auto **Completed**.  
9. Workflow continues from **Task 3** onward (normal uploads, payments, receipts).  
10. When all remaining tasks are done and closure rules pass → Project **Completed**.

**In system:** `bootstrap_sea_task_plan_for_project` after `insert_shipment_project`; `carry_project_shipment_documents_to_sea_tasks` copies Project rows to tasks **1–2**; then `auto_complete_initial_sea_tasks`. Task documents are **read-only** on those tasks (audit copy, no re-upload).

### Task form — fields shown per step

On each sea clearance **Task**, the form only shows fields relevant to that step:

| Field area | Shown when |
|------------|------------|
| **Task Documents** | Operational / documentation tasks; **Supplier Invoice** required on finance tasks |
| **Task Permits** | Tasks **5** and **15** (pre/post clearance permits) — invoice per permit type |
| **Purchase Invoice / Payment Entry** | Finance tasks only (4, 6, 12, 14, 18) — complete via **Make Payment**, not Mark Completed |
| **External Ref No** | Task 3 and later |
| Tasks 1–2 (completed) | Blue intro only; no Mark Completed |

### Task completion rules (enforced on save)

A task **cannot** be set to **Completed** unless:

| Step type | Requirement |
|-----------|-------------|
| **Declaration (e.g. UCR/IDF, Entry)** | Required document types attached on **Task Documents** |
| **Permits (5, 15)** | At least one **Task Permits** row per agency (DVS, NBA, VMD, ACA, SCA) with **Permit Invoice (for Finance)** attached in the grid (not Task Documents) |
| **Finance (4, 6, 12, 14, 18)** | **Supplier Invoice** on task + submitted **Purchase Invoice** + submitted **Payment Entry** (via **Make Payment**) |
| **Coordination (8, 19–24)** | Document, **Description**, or **External Ref** |

**Where Finance sees permit invoices:** Declaration attaches files in **Task Permits → column “Permit Invoice (for Finance)”** on task 5/15. After save, the same files appear on **Project → Regulatory Permits**. Finance task 6 uses **View Permit Invoices on Project** before creating the Purchase Invoice.

### Permit payment workflow (tasks 5 + 6)

| Step | Who | Action | Task status |
|------|-----|--------|-------------|
| 1 | Declaration | Attach **Permit Invoice** on each row → **Notify Finance — invoices ready** | Task 5 stays **Open** |
| 2 | Finance | Email/alert received → open **Finance pays Pre-Clearance Permits** → **Create Purchase Invoice** (permit lines + amounts pre-filled from Task 5) → **Make Payment** | Task 6 stays **Open** after payment |
| 3 | Operations | Upload **Payment Receipt** on each permit row (Task 6 grid) | — |
| 4 | Finance | Tick **Receipt Verified** on each row → **Complete Permit Payment Task** | Task 6 **Completed**; Task 5 auto-closed |

**Notifications:** Finance (invoices ready, verify receipts); Operations (upload receipts after payment).

**Project sync:** **Task Permits** → **Project → Regulatory Permits** automatically:

- **Pre-Cleared** — permit invoice attached (task 5)
- **Post-Cleared** — payment entry submitted + receipt verified (task 6)

**In system:** `task_completion_rules.py`, `task.py` `before_save` / `validate`, `public/js/task.js`.

---

## 4. Project (Central Operations Hub)

The **Project** is the master record for the entire shipment lifecycle — the **shipment file**, not individual tasks.

### Shipment Tracking Sheet (first section on Project)

The top of the **Project** form matches the **LCL tracking spreadsheet** plus a **visual workflow bar** (current status + task progress). See [SHIPMENT_TRACKING_SHEET.md](SHIPMENT_TRACKING_SHEET.md).

| Section | Fields |
|---------|--------|
| **Tracking sheet (top)** | Date, Consignee, CGM Ref, Type, Mode, Status, Client Ref, B/L, AWB, Entry No, IDF No |
| **Transport & timing** | CFS Code (FFK/MCT/…), CFS, weights, ETA, ATA, vessel, shipping line |
| **Charges (text + amount)** | Shipping line charges note, Port/CFS charges note, KEBS, handling/breakbulk |
| **Close-out** | Agent, Date Settled, cargo description, comments |
| **Before vessel berth** | Batch No, Quantity, D.O ref, Custom Release Date, Entry & Taxes note, Berth Phase |
| **Container tracking (after berth)** | HTML table + links to **Container Tracker** rows |
| **Client documents** | `custom_shipment_documents` (CI, PKL, KRA PIN, BL, …) |
| **Regulatory permits** | `custom_permit_register` |

Tasks hold **step-specific** proofs only; the Project holds the **full shipment picture**.

### Container tracking (FCL / Mombasa CNT)

See [CONTAINER_TRACKING_FLOW.md](CONTAINER_TRACKING_FLOW.md).

| Phase | Where | What to capture |
|-------|--------|-----------------|
| **Before berth** | Project header | Client, batch, qty, vessel, ETA, B/L, IDF, permits, line/CFS charges, DO, entry — **not ATA** |
| **After berth** | **Container Tracker** (per container) | Discharge, gate out, warehouse, ICD/transit legs, empty return, demurrage/detention |
| **Seals** | **Seal Record** | Seal no., point (Mombasa/Nairobi/Malaba), quantity |
| **Daily ops** | **Daily Status Update** | Per team counts + RAG (Green/Yellow/Red) → email on Yellow/Red |

**Auto-calculations** on each container: port free days, demurrage days/amount, detention days, expected/actual empty return, overdue status.

It also tracks:

- Tasks (24-step sea plan)
- Payments (Purchase Invoice / Payment Entry on finance tasks + **project** link)
- Linked records (IDF UCR, Customs Entry, containers, KPA, line charges)
- Billing and profitability (Sales Invoice on Project)

---

## 5. Task-Level Document & Sync Logic

### Core rule

- All operational documents are uploaded at **Task** level (`custom_task_documents`)
- The system automatically:
  - Stores the document on the Task
  - Syncs it to the **Project** document repository (`custom_shipment_documents`)

### Task completion rule

A task is marked **Completed** only when:

- Required documents are uploaded on the task
- Finance verification is done (if applicable)
- Payment and receipt requirements are fulfilled (if applicable)

**In system:** Task `on_update` → `refresh_project_shipment_documents`; server validation on Task `before_save` when status → Completed.

---

## 6. Payment Handling (Universal Rule)

For any payable activity:

| Role | Action |
|------|--------|
| Operations | Upload supplier invoice at **Task** level |
| Finance | Verify invoice → Create **Purchase Invoice** → **Payment Entry** |
| Operations | Upload receipt at **Task** level |
| Finance | Verify receipt |
| System | Reconcile PI + PE; allow task completion after confirmation |

**In system:** Finance tasks (4, 6, 12, 14, 18) use **Create Purchase Invoice** / **Make Payment** on the Task:

1. **Create Purchase Invoice** — auto-fills **Project**, **Company**, **CGM Source Task**, and remarks from the task (no manual Project pick).
2. On PI **submit** — links to the task and syncs **Project** on the invoice (and line items).
3. **Make Payment** — builds a Payment Entry via ERPNext `get_payment_entry` against that PI (references + allocation prefilled).
4. On PE **submit** — links PE to the task, verifies allocation against the PI, sets **Project**, marks task **Completed**.

Use **Sync PI Project** on the task if an older PI was created before this linking was enabled.

---

## 7. Permit Management (Pre-Cleared / Post-Cleared)

Each permit is handled as a **Task** (sea task template) and summarized on **Project** → `custom_permit_register`.

### Permit phases (`clearance_phase` on each permit row)

| Phase | Meaning |
|-------|---------|
| **Pre-Cleared** | Invoice attached; finance verified invoice; payment in process or initiated |
| **Post-Cleared** | Payment completed; receipt verified; permit document issued |

**Benefit:** Simple visibility at Project level without tracking micro-steps in the status field.

**Detail status** (optional): Applied → Invoice Verified → Paid → Receipt Verified → Approved / Released.

---

## 8. UCR Process

1. Invoice uploaded at Task level  
2. Finance verifies and processes payment  
3. Receipt uploaded  
4. Task marked **Completed**  
5. Workflow may move to **UCR Applied** / **UCR Paid**

---

## 9. IDF Processing

Proceeds only when:

- UCR is **Completed** (Task 1 + workflow)
- All permits on the project are **Post-Cleared**

Tracked on **IDF UCR Record** (linked to **Project**): IDF number, approval details; supporting documents from tasks (auto-synced).

**In system:** Workflow gate before **Entry Lodged** checks all permit rows are Post-Cleared.

---

## 10. Port & Logistics Tasks

Each activity is a **Task** (port charges, storage, handling, transport, clearance).

Flow: **Invoice → Payment → Receipt → Completion**  
All documents sync to Project automatically.

---

## 11. Transport, Delivery & Container Return

Tracked as Tasks: dispatch, delivery, proof of delivery, container return.  
Managed via Task-level uploads and completion rules.

---

## 12. Customer Billing

When operational work is ready for billing:

- Consolidate Purchase Invoices, expenses, permit costs, logistics charges  
- Generate **Customer Sales Invoice** (linked to **Project**)  
- Include costs, markups, service fees, taxes  

*(Billing consolidation UI — planned; use ERPNext Sales Invoice + Project today.)*

---

## 13. Profitability & Project Closure

System calculates (ERPNext Project):

- Total cost  
- Total revenue  
- Net profit / margin  

---

## FINAL RULE (Project = DONE)

A Project may move to workflow state **Completed** only when **all** of the following are true:

1. **All Tasks** on the project are **Completed** or **Cancelled**
2. **All required Project documents** are **Verified** (synced from tasks)
3. **All permit rows** (if any) are **Post-Cleared**
4. **All payments** for payable tasks are reconciled (Payment Entry submitted where required)
5. **Customer fully invoiced** — at least one **submitted Sales Invoice** linked to the Project

**In system:** Enforced in `enforce_project_closure_on_workflow_change` on Project `before_save`.

---

## Implementation status

| Area | Status |
|------|--------|
| Lead / Opportunity CI-PKL workflows | Implemented |
| Customer KRA PIN → Project sync | Implemented |
| Project master + sea workflow | Implemented |
| Task docs → Project sync | Implemented |
| UCR Task 1 PI / PE / complete | Implemented |
| Permit register + `clearance_phase` | Implemented |
| Project **Completed** closure gate | Implemented |
| Entry Lodged ← all permits Post-Cleared | Implemented |
| Task completion server validation | Implemented |
| Auto-complete sea tasks 1–2 on project create | Implemented |
| Task form shows only relevant fields per step | Implemented |
| Full shipment core fields on Project | Implemented (`v2_3` patch) |
| Auto customer Sales Invoice from costs | Planned |
| Per-permit dedicated Task auto-create | Partial (sea template) |

See also: [SEA_FREIGHT_PROCESS.md](SEA_FREIGHT_PROCESS.md), [TEST_E2E.md](TEST_E2E.md), [RESTRUCTURE.md](RESTRUCTURE.md).
