# Finance Guide

For the **Finance** team: task payments, quotation approval, sales invoice approval, and project cost tracking.

---

## Where to work

| Item | Path in Desk |
|------|----------------|
| Tasks awaiting payment | **Task** (department = Finance, or filter by project) |
| Quotations to approve | **Quotation** → workflow **Pending Finance Approval** |
| Sales invoices to approve | **Sales Invoice** → workflow **Pending Finance Approval** |
| Project cost summary | **Project** → Finance cost total field |
| Journal / payment entries | **Journal Entry**, **Payment Entry** |

---

## Finance tasks in the sea-import plan

| Seq | Task | Payment kind |
|-----|------|--------------|
| 4 | Finance pays UCR | UCR |
| 6 | Finance pays Pre-Clearance Permits | Permit |
| 11 | Finance Pays Entry Slip | Entry |
| 13 | Finance pays Shipping Line Charges | Shipping Line |
| 16 | Finance pays for Post-Clearance Permits | Permit |
| 19 | Finance pays KPA Invoice | KPA |

### Standard payment subflow

Each finance task follows the same pattern:

```
1. Ops/Declaration attaches invoice on the application Task (finance lines / documents)
2. Finance verifies the invoice and creates Journal Entry or Payment Entry
3. Finance uploads payment receipt on the finance Task (Declarant can view it on the application Task)
4. Task can be marked complete → Project status may advance
```

**Task Finance Line** child table holds line items (UCR, permits, entry slip, shipping line, KPA).

Declarants attach invoices (and certificates where required). Finance verifies invoices and uploads payment receipts after payment — no separate receipt-verify step.

### Notifications you receive

ERPNext Notifications alert Finance when invoices are ready, e.g.:

- UCR Invoice to Finance
- Entry Invoice to Finance
- Shipping Line Invoice to Finance
- Permit Invoices to Finance
- KPA Invoice to Finance

---

## Quotation approval

**Workflow:** `CGM Quotation Approval`

| State | Your action |
|-------|-------------|
| **Pending Finance Approval** | Review valuation, customs taxes, local charges → **Approve** or **Reject** |
| **Approved** | Sales can create Sales Order / Sales Invoice |
| **Rejected** | Returns to Draft for correction |
| **Shared with Client** | Client-facing; still billable |

### Billing rule

Sales Order and Sales Invoice can only be created from quotations in:

- **Approved**, or
- **Shared with Client**

Attempting to bill from Draft or Pending Finance Approval is blocked.

### Quotation contents

| Section | Purpose |
|---------|---------|
| Import Cost Component | Foreign-currency valuation (CIF, freight, etc.) |
| Customs Tax Component | Estimated IDF, VAT, RDL, etc. |
| Quotation Item Pricing / Items | Local charges (agency, transport, etc.) |

Print formats: **CGM Quotation Full**, **CGM Quotation Local Charges**.

---

## Sales Invoice approval

**Workflow:** `CGM Sales Invoice Approval` (maker-checker gate before submit)

| Approval state | docstatus | Who can edit |
|----------------|-----------|--------------|
| **Draft** | 0 | Accounts User (preparer) |
| **Pending Approval** | 0 | Accounts Manager only (preparer locked out) |
| **Approved** | 1 | Submitted — ERPNext controls payment status |
| **Cancelled** | 2 | Cancelled via workflow or native Cancel |

### Transitions

| From | Action | To | Role |
|------|--------|-----|------|
| Draft | Submit for Review | Pending Approval | Accounts User |
| Pending Approval | Approve | Approved (submits) | Accounts Manager |
| Pending Approval | Reject | Draft | Accounts Manager |
| Approved | Cancel | Cancelled | Accounts Manager |

Rejection returns to **Draft** (no permanent Rejected state). Rejection reason is mandatory via the Reject dialog.

After **Approve**, ERPNext owns payment **Status**:

| Payment status | Meaning |
|----------------|---------|
| **Unpaid** | Submitted; customer sees it on **My Invoices** |
| **Partly Paid** | Partial payment recorded |
| **Paid** | Fully settled |
| **Overdue** | Past due with balance outstanding |

Workflow uses **Don't Override Status** — the list indicator and customer portal show **Unpaid / Paid**, not the approval state.

Email notifications (queued):

- **Submit for Review** → Accounts Manager
- **Approve** → invoice creator (notes approval + payment status)
- **Reject** → invoice creator (includes rejection reason)

Post-approval corrections: **Cancel → Amend → Draft → Submit for Review → Approve** (full approval cycle again).

---

## Finance cost ledger

Journal Entries linked to a sea task (`custom_cgm_source_task`) automatically update the **Project** finance cost summary (`custom_finance_cost_total`).

| Event | Effect |
|-------|--------|
| JE insert / update / submit | Costs added to project summary |
| JE cancel | Costs reversed |

**Do not** manually edit the finance cost total on Project — the field is protected.

Cost categories are mapped in **CGM Shipping Settings → Finance Cost Category Map**.

---

## Payment Entry rules

- When linking a payment to a shipment, a **Project** reference is required (`validate_shipment_link`).
- Submitting a Payment Entry can auto-complete the linked finance Task when criteria are met.

---

## Journal Entry from tasks

Tasks may expose **Create Journal Entry** actions when finance lines are ready. The JE inherits the source task for ledger sync.

---

## Checklist: finance on a new shipment

- [ ] UCR paid (task 4) after Declaration creates UCR (task 3)
- [ ] Pre-clearance permits paid (task 6)
- [ ] Entry slip paid (task 11) after entry lodged (task 10)
- [ ] Shipping line charges paid (task 13)
- [ ] Post-clearance permits paid (task 16)
- [ ] KPA invoice paid (task 19)
- [ ] Review quotation before client billing
- [ ] Approve sales invoice before submit
- [ ] Monitor project cost total vs budget

---

## Related guides

- [Operations](operations.md)
- [Declaration & Customs](declaration-customs.md)
- [Commercial](commercial.md)
- [Admin & Setup](admin-setup.md)
