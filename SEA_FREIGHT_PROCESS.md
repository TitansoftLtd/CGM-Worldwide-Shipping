# Sea Freight Clearance — CGM Worldwide Shipping

**Master:** Project (`custom_shipment_status` workflow)  
**Operations:** 24 ordered **Tasks** (Sea Task Plan) — must complete **in sequence** before Project can close.

Full business process: [OPERATIONS_PROCESS.md](OPERATIONS_PROCESS.md)

---

## Sea clearance chart (24 tasks)

For **Sea** projects created from approved Lead/Opportunity (CI + PKL on file), the system **auto-creates** the task plan and **auto-completes tasks 1–2**. Use **Generate Sea Task Plan** only if the plan is missing or you need `reset=1`.

Tasks are chained with `depends_on` and `custom_sequence_no` 1–24.

| # | Task | Department | Notes |
|---|------|------------|--------|
| 1 | Receive shipment documents from Client | Operations | **Auto-completed**; CI/PKL/KRA copied from Project |
| 2 | Share documents with Declarants | Operations | **Auto-completed**; same documents (read-only on task) |
| 3 | Create UCR (IDF) | Declaration | **First actionable task** → **UCR Applied** |
| 4 | Finance pays UCR | Finance | Payment task → **UCR Paid** |
| 5 | Apply for Pre-Clearance Permits (DVS, NBA, VMD, ACA) | Declaration | → **Pre-clearance** |
| 6 | Finance pays Pre-Clearance Permits | Finance | Payment task |
| 7 | Client conducts inspection | Operations | → **Client Inspection** |
| 8 | Track shipment and monitor ETA | Operations | → **In Transit** |
| 9 | Receive Final Clearance Documents (B/L, Invoice, PKL, COC) | Documentation | → **Final Docs Received** |
| 10 | Request Manifest and Local Import Charges | Documentation | → **Manifest Requested** |
| 11 | Create Entry (after vessel arrival confirmation) | Declaration | → **Entry Lodged** |
| 12 | Finance pays Shipping Line Charges | Finance | Payment task |
| 13 | Lodge Delivery Order | Operations | → **Line Paid & DO Lodged** |
| 14 | Confirm Entry Payment (Client/CGM) | Finance | Payment task → **Entry Paid** |
| 15 | Prepare and pay Post-Clearance Permits | Declaration | → **Post-clearance** |
| 16 | Field Officers conduct clearance | Field Operations | → **Field Clearance** |
| 17 | Supervisor obtains KPA Invoice | Operations | |
| 18 | Finance pays KPA Invoice | Finance | Payment task → **KPA Paid** |
| 19–24 | Transport / delivery / container return | Transport | → **Completed** when all done |

**Finance tasks (4, 6, 12, 14, 18):** require submitted **Purchase Invoice** + **Payment Entry** on the task before **Completed**.

---

## Workflow actions (`custom_shipment_status`)

Each transition is blocked until the **prior tasks** in the table above are **Completed** (see `SEA_WORKFLOW_TASK_GATES` in code).

| Action | Next status |
|--------|-------------|
| Receive Client Documents | Documents Received |
| Create UCR Application | UCR Applied |
| Confirm UCR Paid | UCR Paid |
| Start Pre-clearance Permits | Pre-clearance |
| Request Client Inspection | Client Inspection |
| Start Shipment Tracking | In Transit |
| Receive Final Documents | Final Docs Received |
| Request Manifest and Charges | Manifest Requested |
| Lodge Customs Entry | Entry Lodged |
| Confirm Line Paid and DO Lodged | Line Paid & DO Lodged |
| Confirm Entry Paid | Entry Paid |
| Complete Post-clearance Permits | Post-clearance |
| Hand to Field Officers | Field Clearance |
| Confirm KPA Paid | KPA Paid |
| Dispatch Cargo | In Delivery |
| Confirm Containers Returned | Containers Returned |
| Complete Shipment File | **Completed** |

---

## Project = DONE (final rule)

**Completed** workflow state requires:

1. All **24** sea tasks **Completed** in order  
2. Required Project documents **Verified**  
3. All permits **Post-Cleared** (if any on file)  
4. Finance tasks reconciled (Payment Entry on payable tasks)  
5. Submitted **Sales Invoice** on the Project  

---

## Regenerate task plan

If a project still has the old 11-task plan:

```bash
# From Project form: Generate Sea Task Plan (with reset via API reset=1)
```

Or delete old sea tasks and regenerate from the button.

Settings template is updated on migrate (`v2_2` patch) under **CGM Shipping Settings → Sea import task template**.
