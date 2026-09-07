---
title: Full documentation
metatags:
  description: Complete CGM Shipping reference — workspace, DocTypes, eight shipment templates, Sea Import flow, funding, guards, roles, notifications, install, and developer paths.
---

# Full documentation

**End-to-end freight forwarding and customs clearance on ERPNext (`cgm_shipping`): CRM intake → multi-mode clearance → containers → quotations/invoicing → funding → portals.**

This page is the comprehensive reference. Role-based day-to-day steps live in the guides linked from the [Documentation Hub](README.md). Every Shipment Type’s task list is in [Shipment Modes](guides/shipment-modes.md). Funding via Material Request is in [Funding Request](guides/funding.md).

To access the Desk workspace, go to:

> Home > CGM Shipping

## 1. Prerequisites

- App installed and migrated (`cgm_shipping`)
- Wiki app optional for `/cgm-shipping/` publishing
- Masters and **CGM Shipping Settings** reviewed

## 2. Features — Where things live

### Desk workspace

**Workspace:** CGM Shipping (`cgm_worldwide_shipping/workspace/cgm_shipping/`)

| Section | Links |
|--------|--------|
| **Shortcuts** | Customer · Project · Bill of Lading · Air Waybill · Opportunity · Container Tracker · **Container Ops Board** · Customs Entry |
| **Shipments** | Project · Bill of Lading · Air Waybill · Export Shipment · Shipment tracker · Daily Status Update |
| **Clearance & Customs** | Customs Entry · IDF UCR Record · Clearance Station · Port Charges KPA Invoice · Shipping Line Charges |
| **Transport & Containers** | Container Tracker · **Container Ops Board** · Seal Record · Interchange Receipt · Report: Container Tracking Detail |
| **Masters & Setup** | Container Type · Shipment Type · Mode of Transport · Document Type · Permit Type · CFS Location · **CGM Shipping Settings** |
| **Pages** | Container Ops Board (`container-ops-board`) · Operations Overview (`operations-overview`) |

Standard ERPNext doctypes used heavily: **Lead**, **Opportunity**, **Customer**, **Project**, **Task**, **Quotation**, **Sales Order**, **Sales Invoice**, **Supplier**, **Item**, **Material Request**, **Journal Entry**, **Payment Entry**, **Leave Application**.

### Reports (selection)

Container Tracking Detail / Report / Return Tracker · Funding Request Report · Material Request Funding · Project Expense Summary · PAYE / NSSF / SHIF Monthly Return · DTB Salary Payment Schedule

### Portals (website)

| Route | Role | Purpose |
|-------|------|---------|
| `/portal` | Customer | Shipment home |
| `/my-shipments`, `/shipment`, `/documents` | Customer | Progress, documents |
| `/my-quotations`, `/my-invoices` | Customer | Commercial docs |
| `/my-messages` | Customer | Messaging |
| `/container` | Customer | Container timeline |
| `/transporter`, `/transporter/allocation`, `/transporter/invoices`, `/transporter/profile` | Transporter | Jobs and invoices |

### Print formats

| Name | DocType | Notes |
|------|---------|-------|
| CGM Quotation Full | Quotation | Valuation + taxes + local charges |
| CGM Quotation Local Charges | Quotation | Local charges only |
| CGM Quotation Shipping | Quotation | Legacy combined layout |
| CGM Sales Invoice Default | Sales Invoice | Branded invoice + QR |
| CGM Sales Invoice | Sales Invoice | Alternate |
| CGM Credit Note | Sales Invoice | Credit notes |
| CGM Purchase Invoice Transporter | Purchase Invoice | Transporter share |

PDF engine: **Chrome** (Frappe 16).

## 3. Features — Eight shipment templates

**Shipment Type** on Opportunity selects **CGM Task Template** + **Container Tracker Mode**. Full subject tables: [Shipment Modes](guides/shipment-modes.md).

| Shipment Type | CGM Task Template | Tracker Mode | Tasks |
|---------------|-------------------|--------------|------:|
| Sea Import | Sea Import Workflow | Mombasa Port | 25 |
| Sea Export | Sea Export Workflow | Export | 14 |
| Air Import | Air Import Workflow | ICD Nairobi | 16 |
| Air Export | Air Export Workflow | Export | 11 |
| Sea Transit Import | Sea Transit Import Workflow | Transit Import | 15 |
| Sea Transit Export | Sea Transit Export Workflow | Transit Export | 10 |
| Road Transit Outbound | Road Transit Outbound Workflow | Transit Export | 10 |
| Road Transit Inbound | Road Transit Inbound Workflow | Transit Import | 13 |

Seed source: `customizations/task_template_seed_data.py` · Registry: `task_template_registry.py`.

**Export Shipment** DocType holds export/transit fields (COC/EAC, C2, exit note, ECMD, warehouses) linked to Project.

## 4. Features — DocTypes & data

### Configuration (single / masters)

| DocType | Purpose |
|---------|---------|
| **CGM Shipping Settings** | Gates, role maps, funding default expense account, cost category map, notifications, sea task requirements |
| **CGM Task Template** | Editable task plans (seed creates missing defaults; site edits preserved) |
| **Shipment Type** | Links template + tracker mode + required docs |
| **Mode of Transport** | Transport mode master |
| **Container Type** / **Container Size** | Container classification |
| **Document Type** | Codes (CI, PKL, UCR, …) |
| **Permit Type** | Client permits → default Item |
| **Customs Tax Type** | VAT, IDF, RDL, … |
| **Clearance Station** / **CFS Location** / **Clearance Port** | CFS / port masters |
| **Material Request Purpose** | Funding classification support |
| **License Settings** | Company licence reminder schedule |

### Transport & shipment records

| DocType | Purpose |
|---------|---------|
| **Bill of Lading** | Sea transport; containers; deposits |
| **Air Waybill** | Air transport |
| **Booking Confirmation** | Planned sea booking |
| **Container Tracker** | Per-container lifecycle |
| **Container Allocation** | Transporter jobs |
| **Export Shipment** | Export/transit field shell |
| **Shipment tracker** | General tracking |
| **Daily Status Update** | Ops RAG (`DSU-{date}-{#####}`) |
| **Seal Record** / **Interchange Receipt** | Seals / empty return |
| **Funding Request** | Batch MR funding |
| **Shipment Update** / **Portal Feedback** | Portal messaging / feedback |
| **Additional Salary Tool** | HR payroll helper |
| **License Register** (+ types, contacts, reminder log) | Company licences |

### Customs & clearance

| DocType | Purpose |
|---------|---------|
| **Customs Entry** | Entry + taxes |
| **IDF UCR Record** | UCR/IDF + finance links |
| **Port Charges KPA Invoice** | KPA charges |
| **Shipping Line Charges** | Line charges |

### Child tables (selection)

Shipment Document · Permit Register · Task Finance Line · Task Container Update · Import Cost Component · Customs Tax Component · Quotation Item Pricing · Shipping Line Free Days / Demurrage / Detention tiers

### Key custom fields on standard DocTypes

| DocType | Notable fields |
|---------|----------------|
| **Opportunity** | `workflow_state`, client documents, B/L/AWB, Shipment Type |
| **Project** | `custom_shipment_status`, `custom_cgm_ref_no`, documents, permits, finance cost total, ETA/ATA |
| **Task** | `custom_task_flow_key`, `custom_sequence_no`, documents/permits/finance/container children |
| **Quotation** / **Sales Invoice** | Valuation/taxes/pricing; approval `workflow_state` |
| **Material Request** | Funding type, Project, Employee (ops expense), link to Funding Request |
| **Journal Entry** | `custom_cgm_source_task`, funding request link where used |
| **Customer** | KRA PIN attachment → `KRA_PIN` |
| **Supplier** | Shipping line charge tables; transporter portal flag |

## 5. How to — Core flows

### A. CRM intake → Project

```
Lead / Opportunity (Shipment Type + documents + transport refs)
  → workflow_state = Approved + Customer party
    → Project + CGM Task Template tasks
```

Guards: one Project per Opportunity; CI + PKL before **Documents Received**. Details: [CRM & Intake](guides/crm-intake.md).

### B. Sea Import clearance (25 tasks)

Applies when Shipment Type uses **Sea Import Workflow**. Deep guides: [Operations](guides/operations.md), [Declaration](guides/declaration-customs.md), [Finance](guides/finance.md), [Transport](guides/transport-containers.md).

| Seq | Task | Department |
|----:|------|------------|
| 1 | Receive shipment documents from Client | Operations |
| 2 | Share documents with Declarants | Operations |
| 3 | Create UCR (IDF) | Declaration |
| 4 | Finance pays UCR | Finance |
| 5 | Apply for Pre-Clearance Permits (DVS, NBA, VMD, ACA) | Declaration |
| 6 | Finance pays Pre-Clearance Permits | Finance |
| 7 | Client conducts inspection | Operations |
| 8 | Receive Final Clearance Documents (B/L, Invoice, PKL, COC) | Documentation |
| 9 | Request Manifest and Local Import Charges | Documentation |
| 10 | Attach Shipping Line Invoice | Documentation |
| 11 | Finance pays Shipping Line Charges | Finance |
| 12 | Create Entry | Declaration |
| 13 | Finance Pays Entry Slip | Finance |
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

**Finance pairs:** 3→4 (UCR), 5→6 (Permit), 10→11 (Shipping Line), 12→13 (ENTRY_SLIP), 15→16 (Permit), 18→19 (KPA).

### C. Funding Request (ops spend)

```
Material Request (Operational Expense | Purchase | Subcontracting)
  → Funding Request (approve amounts)
    → Operational Expense → Journal Entry
    → Purchase / Subcontracting → Purchase Order (only after funding approved)
```

Separate from clearance Task payments. Settings: **Default Operational Expense Account**. Details: [Funding Request](guides/funding.md). Two-path overview: [Finance](guides/finance.md).

### D. Quotation → Sales Invoice

**CGM Quotation Approval** → bill only from **Approved** or **Shared with Client**.  
**CGM Sales Invoice Approval** maker-checker before submit.  
Details: [Commercial](guides/commercial.md), [Finance](guides/finance.md).

### E. Container lifecycle

B/L → Container Tracker → Task container updates → daily demurrage/detention refresh → Container Ops Board. Transporter portal: `/transporter/allocation`.

### F. Finance cost ledger

JE with `custom_cgm_source_task` updates Project `custom_finance_cost_total` (system-managed).

### G. Portals

Customers: `/portal`. Transporters: `/transporter`. Details: [Portals](guides/portals.md).

### H. Leave / Payroll / Licences

- [Leave](guides/leave.md) — employee applications and approval chains  
- [Payroll & HR](guides/payroll-hr.md) — Additional Salary Tool; PAYE/NSSF/SHIF; DTB  
- [Licence & Permit Register](guides/licences.md) — company certificates (≠ shipment Permit Register)

## 6. Features — Guards

### Project

| Guard | Enforces |
|-------|----------|
| Document gate | Verified docs before some status advances |
| Sea workflow task gates | Min completed task seq per status |
| Intake documents | CI + PKL before Documents Received |
| Project closure | All sea tasks complete before Completed |
| Finance cost ledger | Manual total edits blocked |

### Task / buying / commercial

| Guard | Enforces |
|-------|----------|
| Completion requirements | Docs, finance, permits per template/Settings |
| Department permissions | Tasks scoped by department |
| Funding before PO | Purchase/Subcontracting MR need approved Funding Request |
| Shipping Line supplier on PO | Blocked on funded purchase path |
| Quotation / SI workflows | Finance approval before billing / submit |

### Unique / naming

| DocType | Constraint |
|---------|------------|
| Bill of Lading | `bl_number` unique |
| Container Tracker | Name = `container_number` |
| Customs Entry | `entry_number` unique |
| Seal Record | `seal_number` unique |
| Document Type | `code` unique |

## 7. Features — Roles & notifications

Departments on templates: Operations · Declaration · Finance · Documentation · Field Operations · Transport. Role groups in **CGM Shipping Settings**.

Notifications (examples): UCR/Entry/Shipping Line/Permit/KPA invoice & receipt events · Daily Status RAG · Leave chain · Licence expiry · Operational Update.

## 8. How to — Installation & patches

On `bench migrate`, patches seed templates/modes, workflows, schema, print formats, and wiki sync.

`install.after_migrate` re-applies critical schema and portal setup; seeds CGM Task Templates when missing.

## 9. Features — Developer map

| Area | Path |
|------|------|
| Hooks & events | `cgm_shipping/hooks.py` |
| Task templates | `customizations/task_template_registry.py`, `task_template_seed_data.py` |
| Sea / project / tasks | `sea_clearance.py`, `project.py`, `task.py` |
| Funding | `customizations/funding.py`, `funding_workflow.py` |
| Finance subflows | `workflow.py`, `application_finance.py` |
| Quotation / SI | `quotation.py`, `sales_invoice.py` |
| Containers / portals | `container_tracker.py`, `portal.py`, `website.py` |
| Docs → Wiki | `docs/` + `docs/.wiki.json` |
| Client scripts | `public/js/` (one DocType per file) |

Class overrides include Task → `CGMTask`, Quotation → `CGMQuotation`, Sales Order → `CGMSalesOrder`.

### Scheduled jobs (selection)

- Daily: open container metrics; licence expiry reminders; related charge/deposit jobs as configured in hooks

## 10. How to — Quick start (new site)

1. Masters: Shipment Types (all eight) · Document Types · Permit Types · Stations · CGM Shipping Settings · Default Operational Expense Account.
2. CRM: Opportunity → pick **Shipment Type** → approve → Create Project.
3. Clearance: work template tasks; Sea Import finance pairs 3–4, 5–6, 10–11, 12–13, 15–16, 18–19.
4. Funding: MR → Funding Request for non-clearance spend.
5. Commercial: Quotation → approve → SI → approve → submit.
6. Ops: Container Ops Board / Operations Overview; transporter allocations.

## 11. Related Topics

- [Documentation Hub](README.md)
- [Getting Started](guides/process-overview.md)
- [Shipment Modes](guides/shipment-modes.md)
- [Funding Request](guides/funding.md)
