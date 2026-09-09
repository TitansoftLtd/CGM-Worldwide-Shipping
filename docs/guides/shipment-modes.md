---
title: Shipment Modes
metatags:
  description: All eight CGM Shipment Types with CGM Task Templates, Container Tracker Modes, and full task subject tables by department.
---

# Shipment Modes

**Every clearance plan starts from Shipment Type — eight modes, eight CGM Task Templates.**

Use this page when you need the exact task list for Sea Export, Air, Transit, or Road — or when CRM asks which type to pick on Opportunity. Sea Import deep-dives stay in Operations, Declaration, Finance, and Transport; this page is the inventory for **all** modes.

A typical scenario: Sales selects **Air Import** on Opportunity. After approval, the Project gets the **Air Import Workflow** (16 tasks) and tracker mode **ICD Nairobi**. Declaration and Finance run UCR and entry payment pairs; Field clears at the ICD.

To access types and templates, go to:

> Home > CGM Shipping > Shipment Type

Also use:

> Home > CGM Shipping > CGM Task Template

> Home > CGM Shipping > Project

## 1. Prerequisites

- **Shipment Type** masters linked to a **CGM Task Template** and **Container Tracker Mode** (seeded on migrate)
- Opportunity / Project permissions for your role
- For export or transit fields: **Export Shipment** DocType on the Project where used

:::caution
Do not invent task subjects. Plans below match the seeded templates in `task_template_seed_data.py`. Company admins may edit a **CGM Task Template** on the site — always check the live template if behaviour differs.
:::

## 2. How Shipment Type selects the plan

1. On **Lead / Opportunity**, choose **Shipment Type** (Sea Import, Sea Export, Air Import, …).
2. Each type links to:
   - **CGM Task Template** (task subjects, departments, roles, payment kinds)
   - **Container Tracker Mode** (also used as Project Type for tracking)
3. When the Opportunity is **Approved** and a **Project** is created, the task engine builds Tasks from that template.
4. Application tasks (UCR, shipping line invoice, entry, permits, KPA) pair with **Finance Payment** tasks where `payment_kind` is set — Finance cannot pay until the application side is ready.

:::tip
Pick the type **before** you build the document pack. Changing mode after Project creation does not rebuild the task plan.
:::

## 3. Features — Mode summary

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

**Tracker mode masters:** Mombasa Port · ICD Nairobi · Transit Import · Transit Export · Export

## 4. Features — Transport documents by mode

| Mode family | Typical transport doc | Notes |
|-------------|----------------------|--------|
| Sea import / sea transit import | **Bill of Lading** | Confirmed cargo; containers sync to Container Tracker |
| Sea export / planned sea | **Booking Confirmation** and/or B/L | Booking = planned; B/L replaces planned vessel/ETA when confirmed |
| Air import / air export | **Air Waybill** | AWB number and air process tasks |
| Transit / road | Often **None** at intake, then border docs | Use **Export Shipment** for COC/EAC, C2, exit note, ECMD, warehouses |

Intake still expects client documents (CI, PKL, etc.) per Document Type rules. See [CRM & Intake](crm-intake.md).

## 5. Features — Export Shipment DocType

For export and transit legs, link an **Export Shipment** to the **Project** to hold:

- COC/EAC application date
- Uganda entry number
- C2 document, exit note
- Border clearance date
- ECMD device number
- Loading / delivery warehouse

Workspace: **Shipments → Export Shipment**.

## 6. Features — Application ↔ Finance payment pairs

Where the template sets Application / Permit Application and Finance Payment / Permit Finance:

| Pattern | Example (Sea Import) |
|---------|----------------------|
| Declaration applies → Finance pays | Create UCR (3) → Finance pays UCR (4) |
| Documentation attaches invoice → Finance pays | Attach Shipping Line Invoice (10) → Finance pays Shipping Line (11) |
| Permit apply → Permit finance | Pre-clearance permits (5) → Finance pays permits (6) |

Other modes use the same roles with different sequence numbers — see tables below. Clearance payments are **not** Funding Requests; see [Finance](finance.md) and [Funding Request](funding.md).

## 7. How to use — Sea Import (25)

**Template:** Sea Import Workflow · **Mode:** Mombasa Port

Deep process guides: [Operations](operations.md), [Declaration & Customs](declaration-customs.md), [Finance](finance.md), [Transport & Containers](transport-containers.md).

| Seq | Subject | Department |
|----:|---------|------------|
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

Tasks **1–2** are Auto Complete when intake documents are in place. Finance depends only on application pairs (3→4, 5→6, 10→11, 12→13, 15→16, 18→19) so other ops steps can progress in parallel where gates allow.

## 8. How to use — Sea Export (14)

**Template:** Sea Export Workflow · **Mode:** Export

| Seq | Subject | Department |
|----:|---------|------------|
| 1 | Receive booking from shipping line | Operations |
| 2 | Receive invoice and packing list from client | Documentation |
| 3 | Collect empty container from depot | Transport |
| 4 | Weigh truck with empty container | Transport |
| 5 | Loading and stuffing at warehouse | Field Operations |
| 6 | Lodge mother entry (customs export entry) | Declaration |
| 7 | Capture child entry | Declaration |
| 8 | Container armed by KRA and shipping line | Field Operations |
| 9 | Lodge stuffing report with KRA | Declaration |
| 10 | KRA grants pre-advice permission | Field Operations |
| 11 | Finance pays KPA charges - truck enters port | Finance |
| 12 | Entry settled | Declaration |
| 13 | Container scheduled for vessel sailing | Operations |
| 14 | Receive Certificate of Export (COE) | Operations |

## 9. How to use — Air Import (16)

**Template:** Air Import Workflow · **Mode:** ICD Nairobi

| Seq | Subject | Department |
|----:|---------|------------|
| 1 | Receive proforma invoice packing list COA | Documentation |
| 2 | IDF application (UCR) | Declaration |
| 3 | Finance pays UCR | Finance |
| 4 | Apply for pre-clearance permits | Declaration |
| 5 | Finance pays permit invoices | Finance |
| 6 | IDF approved - share with client | Operations |
| 7 | Client inspects and shares draft COC | Operations |
| 8 | Client shares airwaybill | Documentation |
| 9 | Shipment arrival - manifest issued | Operations |
| 10 | Lodge draft entry - share with client | Declaration |
| 11 | Register entry - share e-slip for tax payment | Declaration |
| 12 | Confirm entry taxes paid | Finance |
| 13 | Apply for post-clearance permits | Declaration |
| 14 | Share documents to ground handling team | Field Operations |
| 15 | Clearance - verification and permit removal | Field Operations |
| 16 | Release and entry settlement | Operations |

## 10. How to use — Air Export (11)

**Template:** Air Export Workflow · **Mode:** Export

| Seq | Subject | Department |
|----:|---------|------------|
| 1 | Receive documents from client | Documentation |
| 2 | Get origin and destination address | Operations |
| 3 | Check rates from airlines and select route | Operations |
| 4 | Generate airwaybill number | Declaration |
| 5 | Do customs export entry | Declaration |
| 6 | Take package to airport and export processes | Field Operations |
| 7 | Weigh package and confirm dimensions | Field Operations |
| 8 | Book and pay freight and handling charges | Finance |
| 9 | Hand over shipment to airline | Field Operations |
| 10 | Monitor flight departure | Operations |
| 11 | Obtain manifest and apply for COE | Declaration |

## 11. How to use — Sea Transit Import (15)

**Template:** Sea Transit Import Workflow · **Mode:** Transit Import

| Seq | Subject | Department |
|----:|---------|------------|
| 1 | Receive B/L and import documents | Documentation |
| 2 | Request shipping line charges from B/L | Documentation |
| 3 | Attach shipping line invoice | Documentation |
| 4 | Finance pays shipping line charges | Finance |
| 5 | Request delivery order | Operations |
| 6 | Coordinate transit country tax assessment (Uganda/Tanzania) | Declaration |
| 7 | Create transit entry - destination country team | Declaration |
| 8 | Finance pays transit entry taxes | Finance |
| 9 | Clear with transit customs (URA or destination country) | Field Operations |
| 10 | Obtain C2 and exit note | Declaration |
| 11 | Obtain KPA release order | Field Operations |
| 12 | Book trucks | Transport |
| 13 | Create delivery note | Documentation |
| 14 | Fit ECMD devices and dispatch trucks | Transport |
| 15 | Monitor to border and destination warehouse | Transport |

Payment pairs: shipping line **3→4**, transit entry **7→8**.

## 12. How to use — Sea Transit Export (10)

**Template:** Sea Transit Export Workflow · **Mode:** Transit Export

| Seq | Subject | Department |
|----:|---------|------------|
| 1 | Receive booking and documents from client | Operations |
| 2 | Uganda side prepare entry and UBS permit | Operations |
| 3 | Kenya side prepare COC and EAC certificate | Operations |
| 4 | Uganda side facilitates entry release | Operations |
| 5 | Goods depart Uganda toward Mombasa | Transport |
| 6 | Border crossing and Kenya entry | Field Operations |
| 7 | Goods arrive Mombasa stuffed into container | Field Operations |
| 8 | Lodge Kenya export entry | Declaration |
| 9 | KPA pre-advice and vessel sailing | Finance |
| 10 | Receive Certificate of Export | Operations |

## 13. How to use — Road Transit Outbound (10)

**Template:** Road Transit Outbound Workflow · **Mode:** Transit Export

| Seq | Subject | Department |
|----:|---------|------------|
| 1 | Receive invoice and packing list from client | Documentation |
| 2 | Apply for COC and EAC certificate | Operations |
| 3 | Finance pays COC and EAC fees | Finance |
| 4 | Process destination country entry | Declaration |
| 5 | Destination country releases entry | Operations |
| 6 | Transporter shares truck details | Transport |
| 7 | Generate exit note | Declaration |
| 8 | Obtain C2 document | Declaration |
| 9 | Fit ECMD devices and load trucks | Transport |
| 10 | Track Kenya to border to destination | Transport |

## 14. How to use — Road Transit Inbound (13)

**Template:** Road Transit Inbound Workflow · **Mode:** Transit Import

| Seq | Subject | Department |
|----:|---------|------------|
| 1 | Receive shipment documents | Documentation |
| 2 | IDF application (UCR) | Declaration |
| 3 | Finance pays UCR | Finance |
| 4 | Apply for pre-clearance permits | Declaration |
| 5 | Finance pays pre-clearance permits | Finance |
| 6 | Lodge border or ICD entry | Declaration |
| 7 | Finance pays entry / taxes | Finance |
| 8 | Apply for post-clearance permits | Declaration |
| 9 | Finance pays post-clearance permits | Finance |
| 10 | Border and ICD clearance | Field Operations |
| 11 | Book trucks | Transport |
| 12 | Obtain C2 | Declaration |
| 13 | Monitor delivery to Kenya destination | Transport |

## 15. Related Topics

- [Getting Started](process-overview.md)
- [CRM & Intake](crm-intake.md)
- [Operations](operations.md) — Sea Import status, documents, Ops Board
- [Declaration & Customs](declaration-customs.md)
- [Finance](finance.md)
- [Transport & Containers](transport-containers.md)
- **CGM Task Template** / **Shipment Type** on Desk — live template if site edits differ
