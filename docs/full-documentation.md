# CGM Worldwide Shipping - Feature Documentation

ERPNext app (`cgm_shipping`) for end-to-end freight forwarding and customs clearance: CRM intake → sea-import clearance (25-task plan) → container lifecycle → quotations/invoicing → customer & transporter portals.

> **Role-based guides:** see [README.md](README.md)

---

## 1. Where things live

### Desk workspace

**Workspace:** CGM Shipping (`cgm_worldwide_shipping/workspace/cgm_shipping/`)

| Section | Links |
|--------|--------|
| **Shortcuts** | Customer · Project · Bill of Lading · Air Waybill · Opportunity · Container Tracker · **Container Ops Board** · Customs Entry |
| **Shipments** | Project · Bill of Lading · Air Waybill · Export Shipment · Shipment tracker · Daily Status Update |
| **Clearance & Customs** | Customs Entry · IDF UCR Record · Clearance Station · Port Charges KPA Invoice · Shipping Line Charges |
| **Transport & Containers** | Container Tracker · **Container Ops Board** · Seal Record · Interchange Receipt · Report: Container Tracking Detail |
| **Masters & Setup** | Container Type · Shipment Type · Mode of Transport · Document Type · Permit Type · CFS Location · **CGM Shipping Settings** |

Standard ERPNext doctypes used heavily: **Lead**, **Opportunity**, **Customer**, **Project**, **Task**, **Quotation**, **Sales Order**, **Sales Invoice**, **Supplier**, **Item**, **Journal Entry**, **Payment Entry**.

### Custom page

| Page | Route | Purpose |
|------|-------|---------|
| Container Ops Board | `container-ops-board` | Live container KPIs, filters (client, B/L, batch, station), empty-return tracker |

Backend: `customizations/container_ops_board.py` · Frontend: `page/container_ops_board/container_ops_board.js`

### Reports

- Container Tracking Detail
- Container Tracking Report
- Container Return Tracker

### Portals (website)

| Route | Role | Purpose |
|-------|------|---------|
| `/portal` | Customer | Shipment home |
| `/my-shipments`, `/shipment`, `/documents` | Customer | Progress, documents |
| `/my-quotations`, `/my-invoices` | Customer | Commercial docs |
| `/transporter`, `/transporter/allocation` | Transporter | Container allocations |

Configured in `hooks.py` (`role_home_page`, `on_session_creation`, `before_request`).

### Print formats

| Name | DocType | Notes |
|------|---------|-------|
| CGM Quotation Full | Quotation | Valuation + taxes + local charges |
| CGM Quotation Local Charges | Quotation | Local charges only |
| CGM Quotation Shipping | Quotation | Legacy combined layout |
| CGM Sales Invoice Default | Sales Invoice | Branded invoice + QR |

All use Jinja + `get_doc_qr_code` (`customizations/doc_qr.py`). PDF engine: **Chrome** (Frappe 16).

---

## 2. DocTypes & data

### Configuration (single / masters)

| DocType | Purpose |
|---------|---------|
| **CGM Shipping Settings** | Single doc: 25-step sea task template, task completion rules, workflow gates, role mappings, default customs taxes, finance cost category map |
| **Shipment Type** | Mode, sea-import flag, B/L/AWB rules, CGM ref prefix |
| **Mode of Transport** | Transport mode master |
| **Container Type** / **Container Size** | Container classification |
| **Document Type** | Document codes (CI, PKL, UCR, etc.) with required stage |
| **Permit Type** | Permit types linked to default ERPNext Item |
| **Customs Tax Type** | VAT, IDF, RDL, etc. (seeded) |
| **Clearance Station** / **CFS Location** / **Clearance Port** | CFS / port masters (stations seeded from KRA list) |
| **Charge Item** / **Cost Type** | Charge descriptions for quotations |

### Transport & shipment records

| DocType | Purpose |
|---------|---------|
| **Bill of Lading** | Submittable sea doc; unique `bl_number`; container child table; links Opportunity |
| **Air Waybill** | Submittable air transport doc |
| **Container** | Child: container rows on B/L |
| **Container Tracker** | Per-container lifecycle (dates, demurrage/detention, transporter, empty return); name = `container_number` |
| **Container Allocation** | Submittable: assign containers to transporter for a project/B/L |
| **Export Shipment** | Export-side shipment record |
| **Shipment tracker** | General shipment tracking |
| **Daily Status Update** | Submittable ops RAG status (`DSU-{date}-{#####}`) |
| **Seal Record** | Seal tracking (`seal_number`) |
| **Interchange Receipt** | Empty-container interchange confirmation |

### Customs & clearance

| DocType | Purpose |
|---------|---------|
| **Customs Entry** | Submittable entry with taxes; unique `entry_number` |
| **IDF UCR Record** | UCR/IDF certificate + invoice/receipt workflow |
| **Port Charges KPA Invoice** | KPA port charges |
| **Shipping Line Charges** | Shipping-line charge record |

### Child tables (on Project / Task / Quotation / Supplier)

| DocType | Parent | Purpose |
|---------|--------|---------|
| **Shipment Document** | Project, Task, Opportunity | Document type, initial/final attachments, version status, verify metadata |
| **Permit Register** | Project, Task | Permit invoices, receipts, finance links (PI, JE, PE), verification |
| **Task Finance Line** | Task | Finance payment line items (UCR, permits, entry, shipping line, KPA) |
| **Task Container Update** | Task | Per-container updates on transport tasks (11, 18, 20–26) |
| **Import Cost Component** | Quotation | Foreign-currency valuation lines |
| **Customs Tax Component** | Quotation | Estimated customs tax lines |
| **Quotation Item Pricing** | Quotation | Item-based pricing breakdown |
| **Item Pricing Rule** | Item | Pricing by shipment type / container / qty |
| **Shipping Line Free Days Rule** | Supplier | Free days by destination |
| **Shipping Line Demurrage Tier** | Supplier | Demurrage rate tiers |
| **Shipping Line Detention Tier** | Supplier | Detention rate tiers |

### Settings child tables (on CGM Shipping Settings)

| DocType | Purpose |
|---------|---------|
| **Sea Import Task Template Item** | Subject + department per task seq (1–25) |
| **Sea Clearance Task Requirement Item** | Completion rules per seq (documents, finance, permits, UCR, etc.) |
| **Sea Workflow Task Gate Item** | Maps `custom_shipment_status` → minimum completed task seq |
| **Workflow Stage Requirement Item** | Document verification stages per workflow state |
| **Finance Cost Category Map** | Maps payment items to project cost buckets |
| **Default Customs Tax** | Default tax rates on Settings |
| **CGM Role Item** | Role groupings (Finance, Operations, Declaration) |

### Key custom fields on standard DocTypes

| DocType | Notable fields |
|---------|----------------|
| **Lead** | `custom_ci_attachment`, `custom_pkl_attachment`, `custom_bill_of_lading`, `custom_container_information`, shipment type/mode |
| **Opportunity** | `workflow_state`, `custom_clients_documents`, B/L/AWB, containers, clearance station, consignee |
| **Project** | `custom_shipment_status`, `custom_cgm_ref_no`, `custom_source_opportunity`, shipment documents, permit register, container tracker, finance cost total, ETA/ATA |
| **Task** | `custom_task_flow_key` (`SEA_IMPORT_E2E`), `custom_sequence_no`, task documents/permits/finance lines, container updates |
| **Quotation** | Import cost component, customs taxes, item pricing, shipment refs, `workflow_state` |
| **Sales Invoice** | CGM/client refs, IDF, country of origin, `workflow_state`, finance approval stamps |
| **Customer** | `custom_kra_pin_attachment` → synced to Document Type `KRA_PIN` |
| **Supplier** | Shipping line free days / demurrage / detention child tables |
| **Journal Entry** | `custom_cgm_source_task` (finance cost ledger sync) |

Custom field JSON: `cgm_worldwide_shipping/custom/*.json` · Runtime fields: `customizations/project_layout.py`

---

## 3. The flow

### A. CRM intake → Opportunity → Project

```
Lead (CI + PKL attachments, B/L, containers)
  → Opportunity (client documents, transport refs, workflow approval)
    → [workflow_state = Approved] + Customer party
      → Project (LP reference naming, shipment status workflow)
        → [Sea import] 25-task clearance plan auto-created
```

**Key logic:** `customizations/shipment.py`, `customizations/project.py`, `customizations/documents.py`

**Guards:**
- Opportunity must be **Approved** and party must be **Customer** before Project creation
- One Project per Opportunity
- **CI** and **PKL** documents required before Project reaches **Documents Received**

### B. Sea import clearance (25 tasks)

Applies when Shipment Type has sea-import workflow enabled. Task plan is seeded in **CGM Shipping Settings** and created on the Project by `customizations/sea_clearance.py`.

| Seq | Task | Department |
|-----|------|------------|
| 1 | Receive shipment documents from Client | Operations |
| 2 | Share documents with Declarants | Operations |
| 3 | Create UCR (IDF) | Declaration |
| 4 | Finance pays UCR | Finance |
| 5 | Apply for Pre-Clearance Permits (DVS, NBA, VMD, ACA) | Declaration |
| 6 | Finance pays Pre-Clearance Permits | Finance |
| 7 | Client conducts inspection | Operations |
| 8 | Receive Final Clearance Documents (B/L, Invoice, PKL, COC) | Documentation |
| 9 | Request Manifest and Local Import Charges | Documentation |
| 12 | Create Entry | Declaration |
| 11 | Finance Pays Entry Slip | Finance |
| 12 | Attach Shipping Line Invoice | Documentation |
| 13 | Finance pays Shipping Line Charges | Finance |
| 14 | Lodge Delivery Order | Operations |
| 15 | Prepare Post-Clearance Permits | Declaration |
| 16 | Finance pays for Post-Clearance Permits | Finance |
| 17 | Field Officers conduct clearance | Field Operations |
| 18 | Supervisor obtains KPA Invoice | Operations |
| 19 | Finance pays KPA Invoice | Finance |
| 20 | Book trucks and notify warehouse | Transport |
| 21 | Load trucks and exit port | Transport |
| 22 | Monitor delivery to destination | Transport |
| 23 | Offload cargo | Transport |
| 24 | Return empty container to depot | Transport |
| 25 | Receive interchange confirmation | Transport |

**Project workflow** (`CGM Sea Import Workflow` on `custom_shipment_status`):

Draft → Documents Received → UCR Applied → UCR Paid → Pre-clearance → Client Inspection → In Transit → Final Docs Received → Manifest Requested → Entry Lodged → Entry Paid → Line Paid & DO Lodged → Post-clearance → Field Clearance → KPA Paid → In Delivery → Containers Returned → **Completed**

Each state advance is gated by minimum completed task seq (from Settings) and verified documents where configured.

**Finance subflows** (Ops attaches invoice → Finance pays → receipt verified → task completes):

| Pair | Tasks | Kind |
|------|-------|------|
| UCR | 3 → 4 | UCR |
| Pre-clearance permits | 5 → 6 | Permit |
| Entry slip | 10 → 11 | Entry |
| Shipping line | 12 → 13 | Shipping Line |
| Post-clearance permits | 15 → 16 | Permit |
| KPA invoice | 18 → 19 | KPA |

Modules: `workflow.py`, `application_finance.py`, `workflow_application_finance.py`

**Auto-complete:** Tasks 1–2 complete automatically when documents are in place.

### C. Quotation → Sales Order / Sales Invoice

```
Quotation (import valuation + customs taxes + item pricing + local charges)
  → Submit for Finance Approval
    → Approved / Rejected / Shared with Client
      → Sales Order or Sales Invoice (custom fields mapped)
```

**Workflow:** `CGM Quotation Approval`

| State | Meaning |
|-------|---------|
| Draft | Editable |
| Pending Finance Approval | Awaiting finance |
| Approved | Ready for billing |
| Rejected | Returned to draft |
| Shared with Client | Client-facing; also billable |

**Billing guard:** Sales Invoice / Sales Order only from quotations in **Approved** or **Shared with Client**.

**Logic:** `customizations/quotation.py` · Overrides: `make_sales_order`, `make_sales_invoice` in `hooks.py`

### D. Sales Invoice finance approval

**Workflow:** `CGM Sales Invoice Approval`

Draft → Pending Finance Approval → Approved / Rejected

- **Submit** is blocked until `workflow_state = Approved`
- Finance team is notified on pending approval (`customizations/sales_invoice.py`)

### E. Container lifecycle

```
B/L containers → Container Tracker (per container_number, per project)
  → Task container updates (gate-out, delivery, offload, empty return)
    → Daily scheduler refreshes demurrage/detention metrics
      → Container Ops Board (operations dashboard)
```

**Container statuses** (derived from dates): Pending Arrival → Vessel Berthed → Discharged / At Port → Released / In Transit → At Warehouse → Cargo Offloaded → Empty Returned → Interchange Received (or Return Overdue).

**Transporter portal:** Container Allocation visible at `/transporter/allocation`.

### F. Finance cost ledger

Journal Entry insert/update/submit/cancel syncs costs to **Project** `custom_finance_cost_total` summary.

- Source task linked via `custom_cgm_source_task`
- Project finance ledger is **system-managed** (manual edits blocked)

Module: `customizations/finance_cost_ledger.py`

### G. Customer portal

Website users with role **Customer** land on `/portal` after login. They can view shipment progress, documents, quotations, and invoices. Timezone localization via `portal_localize_time.js`.

---

## 4. Guards in place

### Project

| Guard | Enforces |
|-------|----------|
| Document gate on workflow change | Verified documents before advancing `custom_shipment_status` |
| Sea workflow task gates | Min completed task seq per workflow state |
| Intake documents | CI + PKL before **Documents Received** |
| Permit rules | Post-clearance permit rules before **Entry Lodged** |
| Project closure | All sea tasks complete before **Completed** |
| Finance cost ledger | Manual edits to cost summary blocked |

### Task

| Guard | Enforces |
|-------|----------|
| Completion requirements | Document codes, finance payments, permit rows per seq (from Settings) |
| Settings configured | Throws if completion rules table is empty |
| Department permissions | Users see tasks for their department only |
| Payment Entry submit | Can auto-complete linked finance tasks |

### Quotation / Sales Invoice

| Guard | Enforces |
|-------|----------|
| Customs tax calculation | Validated on save |
| Quotation workflow | Finance approval before sharing / billing |
| Sales Invoice submit | Only when workflow **Approved** |
| Item pricing rules | No overlapping rules on same Item |

### Unique / naming constraints

| DocType | Constraint |
|---------|------------|
| Bill of Lading | `bl_number` unique |
| Container Tracker | Name = `container_number` |
| Customs Entry | `entry_number` unique |
| Seal Record | `seal_number` unique |
| Shipment Type | `shipment_type_name` unique |
| Document Type | `code` unique |

### Payment Entry

- Project link required when shipment-linked (`overrides/payment_entry.py`)

---

## 5. Roles & departments

Task assignment follows **department** on each step of the sea template:

- Operations · Declaration · Finance · Documentation · Field Operations · Transport

Role groupings are configurable in **CGM Shipping Settings** (`CGM Role Item` child table).

Finance actions (approve quotation, approve sales invoice, pay UCR/permits/entry/shipping line/KPA) expect users with Finance roles.

---

## 6. Notifications

ERPNext Notifications (seeded / referenced in `constants.py`) alert teams at key handoffs, e.g.:

- UCR invoice to Finance  
- Entry invoice to Finance  
- Shipping line invoice to Finance  
- Permit invoices to Finance  
- KPA invoice to Finance  
- Daily status RAG alerts  

Dispatcher: `customizations/notifications.py`

---

## 7. Installation & patches

On `bench migrate`, patches in `patches.txt` run idempotently:

| Category | Examples |
|----------|----------|
| **Seed data** | Sea task template, task requirements, workflow gates, clearance stations, CFS locations, customs tax types |
| **Workflows** | Quotation approval, Sales Invoice approval, entry/shipping-line/post-clearance/KPA finance subflows |
| **Schema** | Supplier shipping-line tables, task container updates, quotation pricing fields, print formats |
| **Workspace** | Container Ops Board link |

`install.after_migrate` re-applies critical schema and transporter portal setup.

---

## 8. Developer reference

| Area | Path |
|------|------|
| Hooks & events | `cgm_shipping/hooks.py` |
| Shared constants | `customizations/constants.py` |
| Sea seed defaults | `customizations/sea_settings_seed_data.py` |
| Project / clearance | `customizations/project.py`, `sea_clearance.py` |
| Task engine | `customizations/task.py` |
| Finance subflows | `customizations/workflow.py`, `application_finance.py` |
| Quotation / billing | `customizations/quotation.py`, `sales_invoice.py` |
| Container ops | `customizations/container_tracker.py`, `container_ops_board.py` |
| Portals | `customizations/portal.py`, `transporter_portal.py`, `website.py` |
| Client scripts | `cgm_shipping/public/js/` |
| Patches | `cgm_shipping/patches/` |

### Class overrides

- `Task` → `CGMTask`
- `Quotation` → `CGMQuotation`
- `Sales Order` → `CGMSalesOrder`

### Scheduled jobs

- **Daily:** `container_tracker.refresh_open_container_metrics` - recalculates open container demurrage/detention

---

## 9. Quick start (new site)

1. **Masters:** Shipment Type (enable sea import workflow) · Document Types · Permit Types · Clearance Stations · CGM Shipping Settings (review task template & gates).
2. **CRM:** Lead with CI/PKL → Opportunity → approve workflow → create Project.
3. **Clearance:** Complete tasks in seq; finance subflows on tasks 3–4, 5–6, 10–11, 12–13, 15–16, 18–19.
4. **Commercial:** Quotation → finance approve → Sales Invoice → finance approve → submit.
5. **Operations:** Monitor containers on **Container Ops Board**; allocate transporters via Container Allocation.

---

*App: `cgm_shipping` v0.0.1 · Module: CGM Worldwide Shipping · Built on Frappe / ERPNext 16.*
