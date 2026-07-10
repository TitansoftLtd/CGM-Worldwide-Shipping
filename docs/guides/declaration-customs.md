# Declaration & Customs Guide

For **Declaration** teams handling UCR, permits, customs entry, and regulatory documents.

---

## Where to work

| Item | Path in Desk |
|------|----------------|
| Project / tasks | **Project** → linked **Tasks** (department = Declaration) |
| UCR records | **IDF UCR Record** |
| Customs entries | **Customs Entry** |
| Permit tracking | **Permit Register** on Project / Task |
| Masters | **Permit Type**, **Document Type**, **Clearance Station** |

---

## Your tasks in the sea-import plan

| Seq | Task | Notes |
|-----|------|-------|
| 3 | Create UCR (IDF) | Triggers UCR finance subflow (task 4) |
| 5 | Apply for Pre-Clearance Permits | DVS, NBA, VMD, ACA |
| 10 | Create Entry | After vessel arrival confirmation |
| 15 | Prepare Post-Clearance Permits | After DO lodged |

Finance pays on tasks **4, 6, 11, 16** (not your submit, but you upload receipts). See [Finance Guide](finance.md).

---

## UCR workflow (tasks 3–4)

```
Task 3: Create UCR (IDF)
  → Attach UCR application / certificate documents on Task
  → Finance notified (UCR Invoice to Finance)
Task 4: Finance pays UCR
  → Upload payment receipt
  → Finance verifies
  → Project may advance to UCR Paid
```

**IDF UCR Record** doctype stores UCR/IDF certificate details and links to finance workflow fields.

---

## Permit workflows

### Pre-clearance (tasks 5–6)

1. Apply for permits (DVS, NBA, VMD, ACA) on Task 5.
2. Add rows to **Permit Register** / **Task Permits** child table.
3. Attach permit invoices.
4. Finance pays on Task 6.
5. Upload receipts; Finance verifies.

### Post-clearance (tasks 15–16)

Same pattern after Delivery Order is lodged (task 14).

**Permit Type** master links each permit to a default ERPNext Item for purchase invoice lines.

---

## Entry slip workflow (tasks 10–11)

1. Confirm vessel arrival on Project (ATA / berth confirmation).
2. Create customs **Entry** on Task 10.
3. Attach entry slip invoice.
4. Finance pays on Task 11.
5. Upload receipt; verify.

**Customs Entry** doctype: submittable, unique `entry_number`, tax child table.

---

## Documents you typically handle

| Code | Document |
|------|----------|
| CI | Commercial Invoice |
| PKL | Packing List |
| UCR / IDF | Import Declaration |
| MANIFEST | Cargo manifest |
| DO | Delivery Order |
| COC | Certificate of Conformity |

Upload via **Shipment Document** rows on Project or Task. Documents must reach **Verified** status before some workflow gates open.

---

## Project status gates (declaration-relevant)

| Status | Typical declaration milestone |
|--------|------------------------------|
| UCR Applied | Task 3 complete |
| UCR Paid | Task 4 complete |
| Pre-clearance | Task 5 complete |
| Entry Lodged | Task 10 complete |
| Entry Paid | Task 11 complete |
| Post-clearance | Task 15 complete |

Task sequence minimums are configured in **CGM Shipping Settings → Sea Workflow Task Gates**.

---

## Guards

- Task cannot complete until required document codes are verified (per Settings).
- Permit rows must have invoices/receipts verified before finance tasks complete.
- Post-clearance permit rules are enforced before **Entry Lodged** in some configurations.

---

## Related guides

- [Operations](operations.md)
- [Finance](finance.md)
- [CRM & Intake](crm-intake.md)
