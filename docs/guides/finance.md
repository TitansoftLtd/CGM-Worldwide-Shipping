---
title: Finance
metatags:
  description: Two finance paths — clearance task payments and Funding Request — plus Sea Import payment table, quotation and sales invoice approval, and project cost tracking.
---

# Finance

**Task payments for clearance, Funding Requests for ops spend, plus quotation and sales invoice approval.**

Use this guide when you pay clearance invoices on shipment Tasks, approve commercial documents, or decide whether a spend belongs on a Task or a Funding Request.

A typical scenario: Declaration attaches a UCR invoice on the application Task; you verify it, create a Journal Entry or Payment Entry, upload the receipt on the finance Task, and the Project can advance. Separately, an Operational Expense Material Request is paid through Funding Request — not through a clearance Task.

To access Finance work, go to:

> Home > CGM Shipping > Task

Also use:

> Home > Accounting > Quotation

> Home > Accounting > Sales Invoice

> Home > Accounting > Journal Entry

> Home > CGM Shipping > Funding Request

![Sales Invoice form](../images/sales-invoice-form.png)

## 1. Prerequisites

- Finance / Accounts roles for JE, Payment Entry, quotation and SI workflows
- Notifications enabled for UCR / Entry / Shipping Line / Permit / KPA invoice events
- **CGM Shipping Settings → Finance Cost Category Map** for project cost buckets
- For Funding Request: Default Operational Expense Account (see [Funding Request](funding.md))

## 2. Features — Two finance paths

| Path | Purpose | Key objects |
|------|---------|-------------|
| **(A) Clearance task payments** | Disburse UCR, permits, shipping line, entry slip, KPA (and mode-specific fees) on the shipment plan | Task → finance lines → JE / Payment Entry → receipt on Task |
| **(B) Funding Request** | Ops expense or purchase batches not modelled as clearance Tasks | Material Request → Funding Request → JE (ops expense) or PO (purchase) |

:::caution
Do not pay a clearance invoice only via Funding Request and expect the Task to complete. Application ↔ Finance pairs complete on the Task. Do not use Employee Advance for Funding Request.
:::

:::tip
Other Shipment Types have different finance sequence numbers. See [Shipment Modes](shipment-modes.md) for full task tables; this page keeps the **Sea Import** payment table as the detailed reference.
:::

## 3. How to — Sea Import clearance payments

| Seq | Task | Payment kind |
|----:|------|--------------|
| 4 | Finance pays UCR | UCR |
| 6 | Finance pays Pre-Clearance Permits | Permit |
| 11 | Finance pays Shipping Line Charges | Shipping Line |
| 13 | Finance Pays Entry Slip | ENTRY_SLIP |
| 16 | Finance pays for Post-Clearance Permits | Permit |
| 19 | Finance pays KPA Invoice | KPA |

Application pairs (current seed):

| Pair | Application seq | Finance seq |
|------|----------------:|------------:|
| UCR | 3 | 4 |
| Pre-clearance permits | 5 | 6 |
| Shipping Line | 10 | 11 |
| Entry Slip | 12 | 13 |
| Post-clearance permits | 15 | 16 |
| KPA | 18 | 19 |

### Standard payment subflow

```
1. Ops / Declaration attaches invoice on the application Task (finance lines / documents)
2. Finance verifies the invoice and creates Journal Entry or Payment Entry
3. Finance uploads payment receipt on the finance Task
4. Task can be marked complete → Project status may advance
```

**Task Finance Line** holds line items. Declarants attach invoices (and certificates where required). Optional **client paid directly** flows still require receipt evidence on the Task where configured.

### Notifications

ERPNext Notifications alert Finance when invoices are ready, for example:

- UCR Invoice to Finance
- Entry Invoice to Finance
- Shipping Line Invoice to Finance
- Permit Invoices to Finance
- KPA Invoice to Finance

## 4. How to — Quotation approval

**Workflow:** `CGM Quotation Approval`

| State | Your action |
|-------|-------------|
| **Pending Finance Approval** | Review valuation, customs taxes, local charges → **Approve** or **Reject** |
| **Approved** | Sales can create Sales Order / Sales Invoice |
| **Rejected** | Returns toward Draft for correction |
| **Shared with Client** | Client-facing; still billable |

Sales Order and Sales Invoice can only be created from quotations in **Approved** or **Shared with Client**.

| Section | Purpose |
|---------|---------|
| Import Cost Component | Foreign-currency valuation (CIF, freight, etc.) |
| Customs Tax Component | Estimated IDF, VAT, RDL, etc. |
| Quotation Item Pricing / Items | Local charges (agency, transport, etc.) |

Print formats: **CGM Quotation Full**, **CGM Quotation Local Charges**. See [Commercial](commercial.md).

## 5. How to — Sales Invoice approval

**Workflow:** `CGM Sales Invoice Approval` (maker-checker before submit)

| Approval state | docstatus | Who can edit |
|----------------|-----------|--------------|
| **Draft** | 0 | Accounts User (preparer) |
| **Pending Approval** | 0 | Accounts Manager only (preparer locked out) |
| **Approved** | 1 | Submitted — ERPNext payment status |
| **Cancelled** | 2 | Cancelled via workflow or Cancel |

| From | Action | To | Role |
|------|--------|-----|------|
| Draft | Submit for Review | Pending Approval | Accounts User |
| Pending Approval | Approve | Approved (submits) | Accounts Manager |
| Pending Approval | Reject | Draft | Accounts Manager |
| Approved | Cancel | Cancelled | Accounts Manager |

After Approve, list/portal show **Unpaid / Paid / Partly Paid / Overdue** (Don't Override Status). Customer sees invoices on **My Invoices** when submitted.

## 6. Features — Cost ledger and Payment Entry

Journal Entries linked to a sea task (`custom_cgm_source_task`) update **Project** `custom_finance_cost_total`. Do **not** edit that total manually.

- Payment Entry against a shipment requires a **Project** reference where validation applies.
- Submitting a Payment Entry can auto-complete the linked finance Task when criteria are met.
- Tasks may expose **Create Journal Entry** when finance lines are ready.

Report: **Project Expense Summary**.

## 7. Checklist — Sea Import finance

- [ ] UCR paid (4) after Declaration creates UCR (3)
- [ ] Pre-clearance permits paid (6)
- [ ] Shipping line paid (11) after attach invoice (10)
- [ ] Entry slip paid (13) after Create Entry (12)
- [ ] Post-clearance permits paid (16)
- [ ] KPA paid (19)
- [ ] Quotation approved before client billing
- [ ] Sales Invoice approved before submit
- [ ] Ops spend via [Funding Request](funding.md) when not a clearance Task

## 8. Related Topics

- [Funding Request](funding.md)
- [Shipment Modes](shipment-modes.md) — finance tasks on other modes
- [Declaration & Customs](declaration-customs.md)
- [Commercial](commercial.md)
- [Operations](operations.md)
