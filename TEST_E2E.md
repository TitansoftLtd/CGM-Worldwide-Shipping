# CGM Worldwide Shipping — End-to-end test guide

## 1. Load test data (one command)

```bash
cd ~/frappe-bench
bench --site cgm.local execute cgm_shipping.cgm_worldwide_shipping.test_data.seed_e2e_test_data.seed
```

This creates:


| Record                                       | How to find it                      | Starting status           |
| -------------------------------------------- | ----------------------------------- | ------------------------- |
| Customer **Abyssinia Iron Steel Ltd (Test)** | CRM → Customer                      | —                         |
| **Sea FCL** Shipment Dossier                 | Client Ref: `E2E-TEST-2026-SEA-FCL` | **Draft**                 |
| **Air Import** Shipment Dossier              | Client Ref: `E2E-TEST-2026-AIR`     | **Documents Received**    |
| Container **TESTU1234567**                   | Linked to sea dossier               | Auto-calculated           |
| IDF, Customs Entry, Shipping Line, KPA       | Linked to sea dossier               | —                         |
| **Daily Status Update** (Red)                | Submitted today                     | Triggers supervisor email |


Re-running the script is safe; it skips duplicates.

---

## 2. Test users (required for workflow)

Workflow buttons appear **only for the role listed** on each transition. Create users (or use existing) and assign **one role each**:


| Login (example)        | Role               | Used for actions                           |
| ---------------------- | ------------------ | ------------------------------------------ |
| `ops.manager@test.cgm` | Operations Manager | Receive Documents, Mark In Transit, Settle |
| `declarant@test.cgm`   | Declarant          | Open IDF, Pre-clearance, Lodge Entry       |
| `finance@test.cgm`     | Finance User       | Confirm Taxes Paid                         |
| `field@test.cgm`       | Field Officer      | Start Clearance, Release Cargo             |
| `transport@test.cgm`   | Transport Officer  | (Released state edit; container work)      |


**Setup:** Setup → Users → open user → Roles → add role.  
**Shortcut:** Use **Administrator** to walk through everything first, then repeat key steps with role-specific users to confirm permissions.

Enable outgoing email (or open **Email Queue**) if you want to verify Red RAG / workflow emails.

---

## 3. Shipment Clearance Workflow — what to test

Workflow: **Shipment Clearance Workflow** on **Shipment Dossier**  
Field updated: **Status** (workflow overrides the status select when active)

### Full path (use Sea FCL dossier `E2E-TEST-2026-SEA-FCL`)


| Step | Action button           | Role               | Status after           | What to verify                                                                 |
| ---- | ----------------------- | ------------------ | ---------------------- | ------------------------------------------------------------------------------ |
| 0    | —                       | Ops                | **Draft**              | Naming like `CGM/FCL-2026-05-00001`; permits table has KEBS + Port Health rows |
| 1    | **Receive Documents**   | Operations Manager | **Documents Received** | Status changes; optional workflow email (if email configured)                  |
| 2    | **Open IDF**            | Declarant          | **IDF Open**           | Open linked **IDF UCR Record** — UCR payment still Pending                     |
| 3    | **Start Pre-clearance** | Declarant          | **Pre-clearance**      | Permit rows visible on dossier                                                 |
| 4    | **Mark In Transit**     | Operations Manager | **In Transit**         | Set **ATA** on dossier if testing arrival                                      |
| 5    | **Lodge Entry**         | Declarant          | **Entry Lodged**       | **Customs Entry** `26NBOIM409252569` aligns with dossier Entry No              |
| 6    | **Confirm Taxes Paid**  | Finance User       | **Taxes Paid**         | Record **Payment Entry** with **Shipment Dossier** = this dossier              |
| 7    | **Start Clearance**     | Field Officer      | **Clearance**          | KRA/KEBS fields on Customs Entry                                               |
| 8    | **Release Cargo**       | Field Officer      | **Released**           | **Port Charges KPA Invoice** — gate pass / payment dates                       |
| 9    | **Settle**              | Operations Manager | **Settled**            | Set **Date Settled**; dossier may move to **Submitted** (docstatus 1)          |


### Negative tests (permissions)

- Log in as **Declarant** on a **Draft** dossier → you should **not** see **Receive Documents**.
- Log in as **Finance User** before **Entry Lodged** → you should **not** see **Confirm Taxes Paid**.
- Wrong role → action hidden or “Not permitted”.

### Air dossier shortcut (`E2E-TEST-2026-AIR`)

Starts at **Documents Received**. Pick up from step **2 (Open IDF)** with **Declarant** — good for testing mid-flow without clicking step 1.

---

## 4. Container Tracker — demurrage & status

Open **Container Tracker** → `TESTU1234567` (linked to sea dossier).

**Seed dates (relative to today):**

- Discharging: 10 days ago  
- Gate out (port): 5 days ago  
- Free days: **5**

**After save, check:**


| Field                     | Expected logic                                                            |
| ------------------------- | ------------------------------------------------------------------------- |
| **Expected Empty Return** | Gate out + 5 free days                                                    |
| **Demurrage Days**        | `max(0, (gate_out − discharge) − free_days)` → with seed data often **0** |
| **Demurrage Amount**      | Demurrage days × **Daily Demurrage Rate** (150)                           |
| **Status**                | **Dispatched** (gate out set, no delivery yet)                            |


**Force overdue test:** Clear **Actual Empty Return**, set **Expected Empty Return** to yesterday → save → **Status** = **Overdue**.

**Empty returned test:** Set **Actual Empty Return** = today → **Status** = **Empty Returned**; **Detention Days** = days from gate out to return.

Then create **Interchange Receipt** linked to this container + dossier.

---

## 5. Daily Status Update — Red RAG email

The seed script submits one **Red** update for Transport.

**Check:**

1. **Email Queue** (Setup → Email Queue) for subject about Red RAG / Operations Manager recipients.
2. If no SMTP: no email, but document should be **Submitted** without error.
3. Submit a **Green** update manually — no alert expected.

---

## 6. Payment Entry link

1. Accounting → **Payment Entry** → New.
2. Set **Shipment Dossier** = sea FCL dossier.
3. Save — should succeed.
4. Clear link, set invalid dossier name — save should **fail** validation.

---

## 7. Quotation (freight) custom fields

Sales → **Quotation** → New.

Fill **Freight Type** (Airfreight / LCL / FCL), **Incoterm**, **Notes / Clauses**, link **Shipment Dossier** after the job exists.

---

## 8. Manual sample data (if not using seed script)

### Sea FCL — Shipment Dossier


| Field            | Sample value               |
| ---------------- | -------------------------- |
| Series           | `CGM/FCL-.YYYY.-.MM.-.###` |
| Shipment Type    | Sea FCL                    |
| Client           | Any Customer               |
| Client Reference | `AISL/AR/11/10486/22`      |
| AWB / B/L        | `SIGMOMB24051234`          |
| Entry No         | `26NBOIM409252569`         |
| CFS              | Siginon                    |
| CFS Code         | SIG                        |
| Vessel           | `MV EVER GOLDEN`           |


### Air Import — Shipment Dossier


| Field         | Sample value              |
| ------------- | ------------------------- |
| Series        | `CGM/IM-.YYYY.-.MM.-.###` |
| Shipment Type | Air Import                |
| AWB / B/L     | `176-12345678`            |
| CFS           | FedEx                     |
| CFS Code      | MAT                       |
| Flight        | `KQ 102`                  |


### Container Tracker


| Field                | Sample value  |
| -------------------- | ------------- |
| Container Number     | `MSKU9876543` |
| Mode                 | Mombasa Port  |
| Free Days            | 7             |
| Daily Demurrage Rate | 200           |


---

## 9. Desk navigation checklist

- **CGM Worldwide Shipping** workspace opens; shortcuts work  
- **Shipment Dossier** list filter by Status  
- Workflow actions visible on form (top right / Actions)  
- Linked child records open from list filters (`shipment_dossier` = …)  
- Version history on dossier (**Track Changes** enabled)

---

## 10. Known gaps (not failures)

These are planned in the guide but **not** built yet — do not expect them during UAT:

- Operations / Transport / Finance **dashboards**  
- Six **reports** (tracking sheet, demurrage report, etc.)  
- Automatic notifications for IDF approved / demurrage > 0 (only Red daily status is implemented)  
- Migration from old **Project** / **Shipment tracker** records

---

## 11. Clean up test data

```bash
bench --site cgm.local console
```

```python
import frappe
marker = "E2E-TEST-2026"
for dt in ["Daily Status Update", "Interchange Receipt", "Container Tracker",
           "Port Charges KPA Invoice", "Shipping Line Charges", "Customs Entry",
           "IDF UCR Record", "Seal Record", "Export Shipment"]:
    for name in frappe.get_all(dt, filters={"shipment_dossier": ["like", f"%{marker}%"]}, pluck="name"):
        frappe.delete_doc(dt, name, force=1)
for name in frappe.get_all("Shipment Dossier", filters={"client_reference": ["like", f"%{marker}%"]}, pluck="name"):
    frappe.delete_doc("Shipment Dossier", name, force=1)
frappe.db.commit()
```

