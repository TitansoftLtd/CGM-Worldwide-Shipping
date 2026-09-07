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
| 12 | Create Entry | Entry Slip invoice + ENTRY document |
| 15 | Prepare Post-Clearance Permits | After DO lodged |

Finance pays on tasks **4, 6, 11, 16**. You upload invoices (and certificates); Finance uploads payment receipts after paying. See [Finance Guide](finance.md).

---

## UCR workflow (tasks 3–4)

```
Task 3: Create UCR (IDF)
  → Attach UCR invoice on Task; attach IDF certificate when issued
  → Finance notified (UCR Invoice to Finance)
Task 4: Finance pays UCR
  → Finance records payment, uploads payment receipt, and verifies
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

## Entry slip workflow (tasks 12–13)

1. Attach Entry Slip invoice on Task 12 (Create Entry).
2. Finance verifies the invoice on Task 13 - Create Entry completes automatically.
3. Finance pays (or client-pays) and uploads receipt on Task 13.
4. ENTRY customs document on Create Entry Clearance Documents remains optional when issued.

Port arrival / ATA is confirmed separately on the **Project** (Actions → Confirm Shipment Arrival at the Port) and does not complete Create Entry.

**Customs Entry** doctype: submittable, unique `entry_number`, tax child table.

---

## The declaration run, start to finish

The tasks above in the order they actually happen:

1. **Commercial invoice** in hand, so the shipment can be quoted.
2. **Open the IDF** for inspection.
3. **Draft B/L** to confirm the shipment; the **original B/L** follows after vessel arrival.
4. Collect the rest as they arrive: commercial invoice, packing list, **COC**, marine insurance cover, **COO**, **COA**.
5. **Wait for the manifest** from the shipping line. Nothing below can start without it.
6. **Create the entry** once the manifest is in - this generates the **e-slip** and the taxes.
7. **Taxes paid**, then check for any permits still outstanding and process them.
8. Hand the file to **Field Operations**, who secure the verification memo and take it through KRA, KPA and the agencies. See [Field clearance](operations.md#field-clearance).
9. Back with you at the end: the **examination account** is input, the file is escalated to the **CRO** for release, port charges are secured and paid, and the gate pass is prepared.
10. **Port pass to border control** releases the entry for final removal, and the truck is loaded.

---

## Air freight declaration

Air runs the same shape with a different document set and an extra client approval before registering the entry:

1. Receive **proforma invoice**, **packing list**, **COA**.
2. **Confirm the documents** - HS code against the product description, and weight against the package count. This is the check that prevents an amended entry later.
3. **IDF application**, then **pay the UCR**.
4. **Apply for pre-clearance permits** and pay the permit invoices.
5. **IDF approved**, then shared with the Operations Manager to forward to the client.
6. Client inspects the shipment and shares the **draft COC**.
7. Once the draft COC is approved, the client shares the **air waybill**.
8. **Flight arrives**, arrival confirmed, manifest issued.
9. **Draft entry lodged** and shared with the client for approval before it is registered.
10. **Entry registered** after the client approves; the e-slip goes to the client to pay the taxes.
11. **Post-clearance permits** applied for after taxes are paid.
12. Passed entry and permits, pre and post, go to the **ground handling team** for clearance.
13. Follow up on permit removal and any holds, exactly as for sea.
14. **Release**, then monitor the entry settling in the system.

The difference that matters: on air, the **client approves the draft entry before it is registered**. On sea the entry is created and registered off the manifest without that round trip.

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
