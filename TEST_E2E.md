# CGM Worldwide Shipping — End-to-end test guide

## Model

- **Master:** ERPNext **Project** (`custom_mode_of_transport` = Sea / Air)
- **Status / workflow:** **CGM Sea Import Workflow** → `custom_shipment_status`
- **Client docs (CI, PKL):** `custom_shipment_documents` on Project
- **Regulatory permits (DVS, NBA, KEBS, Port Health, …):** `custom_permit_register` on Project
- **Operational steps:** **Task** list (Sea Task Plan button on Sea projects)
- **Linked records:** IDF UCR Record, Customs Entry, Container Tracker, Shipping Line Charges, Port Charges KPA — all link to **Project**

See [OPERATIONS_PROCESS.md](OPERATIONS_PROCESS.md) for the full process.  
See [SEA_FREIGHT_PROCESS.md](SEA_FREIGHT_PROCESS.md) for the workflow state map.

---

## 1. Load test data

```bash
cd ~/frappe-bench
bench --site cgm.local migrate
bench --site cgm.local clear-cache
bench --site cgm.local execute cgm_shipping.cgm_worldwide_shipping.test_data.seed_e2e_test_data.seed
```

| Record | How to find | Starting `custom_shipment_status` |
|--------|-------------|-----------------------------------|
| Customer **Abyssinia Iron Steel Ltd (Test)** | CRM → Customer | — |
| **Sea FCL** Project | Client Ref `E2E-TEST-2026-SEA-FCL` | **Draft** |
| **Air Import** Project | Client Ref `E2E-TEST-2026-AIR` | **Documents Received** |
| Container **TESTU1234567** | Linked to sea project | — |
| IDF, Customs Entry, line/KPA charges | Linked to sea project | — |

Re-running the script is safe (skips duplicates).

---

## 2. Test users

Workflow actions appear only for the role on each transition. Example logins:

| Role | Typical actions |
|------|-----------------|
| Operations Manager | Receive Client Documents, manifest, Complete Shipment File |
| Declarant | Create UCR Application, permits, Lodge Customs Entry |
| Finance User | Confirm UCR Paid, Confirm Entry Paid, Confirm KPA Paid |

**Task completion:** regulatory/finance tasks cannot complete without attachments — Supplier Invoice on finance tasks; **Task Permits** + invoice on tasks 5/15; required doc types on declaration steps (see [OPERATIONS_PROCESS.md](OPERATIONS_PROCESS.md)).

**Finance Task 6 — Create Purchase Invoice:** permit types and **Invoice Amount** from Task 5 / Project are pre-filled on the PI **Items** table (one line per permit: DVS, NBA, VMD, ACA).
| Field Officer | Field Clearance |
| Transport Officer | Dispatch Cargo, Confirm Containers Returned |

Use **Administrator** first, then repeat with role-specific users.

---

## 3. Sea FCL walkthrough (`E2E-TEST-2026-SEA-FCL`)

Open **Project** → filter Sea + client ref.

| Step | Workflow action | Role | Status after |
|------|-----------------|------|--------------|
| 0 | — | — | **Draft** (CI/PKL rows seeded; attach files before step 1) |
| 1 | **Receive Client Documents** | Operations Manager | **Documents Received** |
| 2 | *(auto)* Sea task plan + **Tasks 1–2 completed** when CI/PKL from CRM | System | — |
| 3 | Open **Task 3** (Create UCR), complete, then **Create UCR Application** | Declarant | **UCR Applied** |
| 4 | Complete **Task 4** (Finance pays UCR), then **Confirm UCR Paid** | Finance | **UCR Paid** |
| 4 | **Confirm UCR Paid** | Finance User | **UCR Paid** |
| 5+ | Continue per `SEA_FREIGHT_PROCESS.md` | … | Pre-clearance → … → **Completed** |

**Before workflow → Completed:** all **24** sea tasks **Completed in order**, required docs **Verified**, all permits **Post-Cleared**, finance tasks (4, 6, 12, 14, 18) have submitted **Payment Entry**, and a submitted **Sales Invoice** on the Project. See [SEA_FREIGHT_PROCESS.md](SEA_FREIGHT_PROCESS.md).

**Negative tests**

- **Receive Client Documents** without CI/PKL attachments → blocked by server validation.
- **Create UCR Application** without Sea Task Plan / Task 1 completed → blocked on Sea projects.

### Air project (`E2E-TEST-2026-AIR`)

Starts at **Documents Received** — use for mid-flow tests (UCR, permits) without step 1.

---

## 4. What to verify on linked doctypes

| DocType | Check |
|---------|--------|
| **IDF UCR Record** | `project` set; UCR payment status |
| **Customs Entry** | Entry number `26NBOIM409252569` |
| **Container Tracker** | Demurrage auto-calc from gate-out |
| **Payment Entry** | Standard **Project** field (not Shipment Dossier) |

---

## 5. Deprecated

**Shipment Dossier** is inactive for new work; existing rows were migrated to **Project** where possible. Do not train users on dossier workflow for new files.
