---
title: Declaration & Customs
metatags:
  description: UCR, permits, and customs entry for Declaration — Sea Import task pairs with note that sequence numbers differ by Shipment Type.
---

# Declaration & Customs

**UCR (IDF), permits, customs entry, and regulatory documents for Declaration.**

Use this guide for Sea Import declaration work. Other modes reuse Application ↔ Finance patterns with **different sequence numbers**.

A typical scenario: You create the UCR on task 3, attach the invoice and IDF certificate; Finance pays on task 4. Later you Create Entry (12) and Finance pays the entry slip (13). Pre- and post-clearance permits follow the same apply → pay pattern.

To access Declaration work, go to:

> Home > CGM Shipping > Task

Also use:

> Home > CGM Shipping > IDF UCR Record

> Home > CGM Shipping > Customs Entry

## 1. Prerequisites

- Declaration department role
- Permit Type and Document Type masters
- Clearance Station / CFS as required
- Project tasks created from the correct Shipment Type template

:::tip
Task sequence numbers below are **Sea Import**. For Air Import, Transit, Road, and Export declaration steps, see [Shipment Modes](shipment-modes.md).
:::

## 2. How to — Sea Import declaration tasks

| Seq | Task | Notes |
|----:|------|-------|
| 3 | Create UCR (IDF) | Triggers UCR finance (task 4) |
| 5 | Apply for Pre-Clearance Permits | DVS, NBA, VMD, ACA |
| 12 | Create Entry | Entry Slip invoice + ENTRY document |
| 15 | Prepare Post-Clearance Permits | After DO lodged |

Finance pays on tasks **4, 6, 13, 16** (and shipping line **11** is Documentation → Finance). See [Finance](finance.md).

:::note
In older docs, Create Entry was sometimes listed as task 10. Current seed: **Attach Shipping Line Invoice = 10**, **Create Entry = 12**, **Finance Pays Entry Slip = 13**.
:::

## 3. How to — UCR (tasks 3–4)

```
Task 3: Create UCR (IDF)
  → Attach UCR invoice; attach IDF certificate when issued
  → Finance notified
Task 4: Finance pays UCR
  → Payment + receipt on finance Task
  → Project may advance to UCR Paid
```

**IDF UCR Record** stores certificate and finance link fields.

## 4. How to — Permits

### Pre-clearance (5–6)

1. Apply on Task 5; add **Permit Register** / Task Permits rows.
2. Attach permit invoices.
3. Finance pays on Task 6.

### Post-clearance (15–16)

Same pattern after Delivery Order (task 14).

**Permit Type** links each permit to a default ERPNext Item.

## 5. How to — Entry slip (12–13)

1. Attach Entry Slip invoice on Task 12 (Create Entry).
2. Finance verifies and pays on Task 13 (or client-pays with receipt).
3. Port ATA is confirmed separately on **Project** — it does not complete Create Entry.

**Customs Entry:** submittable, unique `entry_number`, tax child table.

## 6. Features — Documents and gates

| Code | Document |
|------|----------|
| CI | Commercial Invoice |
| PKL | Packing List |
| UCR / IDF | Import Declaration |
| MANIFEST | Cargo manifest |
| DO | Delivery Order |
| COC | Certificate of Conformity |

| Status | Typical declaration milestone (Sea Import) |
|--------|--------------------------------------------|
| UCR Applied | Task 3 complete |
| UCR Paid | Task 4 complete |
| Pre-clearance | Task 5 complete |
| Entry Lodged | Create Entry complete (seq 12) |
| Entry Paid | Task 13 complete |
| Post-clearance | Task 15 complete |

Gates: **CGM Shipping Settings → Sea Workflow Task Gates**.

## 7. Features — Guards

- Required document codes must be verified before task complete (per Settings).
- Permit invoices/receipts verified before finance tasks complete.
- Company **License Register** is unrelated — see [Licence & Permit Register](licences.md).

## 8. Related Topics

- [Shipment Modes](shipment-modes.md)
- [Operations](operations.md)
- [Finance](finance.md)
- [CRM & Intake](crm-intake.md)
