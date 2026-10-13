---
title: Funding Request
metatags:
  description: Raise Material Requests, batch them on Funding Request, approve amounts, and pay via Journal Entry or Purchase Order - separate from clearance task payments.
---

# Funding Request

**Batch Material Requests for approval and payment - operational expense by Journal Entry, purchase by Purchase Order after funding is approved.**

Use this guide when you need cash or a purchase that is **not** a clearance task payment (UCR, shipping line, entry slip, KPA, permits on Tasks). Employee Advance is **not** used for this path.

A typical scenario: An officer raises an Operational Expense Material Request for field disbursements against a Project. Finance pulls open requests onto a Funding Request, an approver sets approved amounts, and Finance posts a Journal Entry to the Default Operational Expense Account.

To access Funding Request, go to:

> Home > CGM Shipping > Funding Request

Also use:

> Home > Stock > Material Request

> Home > Accounting > Journal Entry

> Home > Buying > Purchase Order

![Funding Request list](../images/funding-request-list.png)

## 1. Prerequisites

- **Material Request Purpose** masters as used on site
- User linked to an **Employee** (required for Operational Expense)
- Role to create Material Requests; **Funding Approver** (or site workflow roles) for approval
- **CGM Shipping Settings → Default Operational Expense Account** set for JE posting
- Optional: Project on the Material Request for cost tracking

:::note
Clearance invoices on shipment Tasks use [Finance](finance.md) task payments - not Funding Request.
:::

## 2. How to - choose request type

| Material Request type | After funding approval | Payment / buy path |
|----------------------|------------------------|--------------------|
| **Operational Expense** | Amounts approved on Funding Request | **Journal Entry** (expense + bank/cash). No warehouse / stock indent. May be [multicurrency](#4-how-to---request-in-a-foreign-currency). |
| **Purchase** | Funding must be approved | **Purchase Order** (then PI / Payment Entry as usual) |
| **Subcontracting** | Funding must be approved | **Purchase Order** (same funding gate as Purchase) |

### Operational Expense rules

- Set **Employee** (who receives the cash). Link your User on the Employee record if the field should fill automatically.
- Warehouses are cleared - this is not a stock indent.
- Project can sit on the header (`custom_project`) and copies to item Project dimensions.
- **Multicurrency (Funding Request)** is on by default, so a line may be requested in a currency other than the company's. See [section 4](#4-how-to---request-in-a-foreign-currency).

### Purchase / Subcontracting rules

- You **cannot** create a Purchase Order (or related RFQ / supplier quotation helpers CGM overrides) until the linked Funding Request is **approved**.
- Shipping Line suppliers cannot be used on these Purchase Orders.

## 3. How to - create and approve funding

![A new Funding Request: 1 the Material Requests table, 2 Save. Get Material Requests, beside Save, fills the table](../images/funding-request-new.png)

```
Material Request (Submit)
  → Funding Request (pull / Get Material Requests)
    → Approver sets Approved / Rejected amounts per line
      → Disburse
          Operational Expense → Journal Entries created and submitted
          Purchase / Subcontracting → draft Purchase Orders created
```

1. Create and **Submit** each Material Request with the correct type, items, amounts, and Project where relevant.
2. Open **Funding Request** (`FR-.YYYY.-…`) → add submitted Material Requests that are waiting for funding.
3. Submit the Funding Request into the site’s approval workflow (Pending Approval → Approved / Rejected, etc.).
4. Approvers set **approved** (or rejected) amounts per request line - not only a header yes/no.
5. After approval:
   - **Actions > Disburse** on the Funding Request. Operational Expense rows are paid by Journal Entry (using the Default Operational Expense Account when configured); Purchase and Subcontracting rows get a Purchase Order. See [Disbursing](#disbursing).

:::tip
Use **Funding Request Report** and **Material Request Funding** reports to see what is unfunded, on a request, or disbursed.
:::

A funding request gathers the Material Requests it is paying for:

![A Funding Request, showing the Material Request rows with requested amounts and decisions](../images/funding-request-form.png)

**1** Each row carries its own **decision** and **approved amount**, so a request can be
part-approved without rejecting the whole batch. The Material Requests it draws from:

![The Material Request list, showing requests by type and status](../images/material-request-list.png)

## 4. How to - request in a foreign currency

![A Funding Request with two currencies: 1 Totals by Currency, 2 Outstanding in company currency](../images/funding-request-totals.png)

Some operational expenses are billed in US dollars: shipping line charges and KPA
charges are the usual ones, and the company holds USD bank accounts for them.

**Multicurrency (Funding Request) is on by default** on an Operational Expense
Material Request, so every item line carries a **Currency** and an **Exchange
Rate** without anyone having to remember to switch it on. Pick the item, then set
the currency on that line and type the rate. Lines stay in the company currency
until you change one, so a shilling request looks and behaves exactly as it always
did.

The rate typed here is an estimate. It exists so the approver can see a shilling
figure, and it is not the rate that reaches the ledger.

The option is only shown on an Operational Expense request, because that is the
only type funded by Journal Entry rather than a Purchase Order, and a Purchase
Order in this flow is always raised in the company currency. Untick it to force
every line back to the company currency.

**Leave the Exchange Rate blank on a foreign line and today's rate is fetched on
save.** It deliberately has no default: a default of 1 would look filled in and
quietly value USD 1,000 at KES 1,000.

The expense account belongs to the **line**, not to the currency, so the two halves
of a mixed request usually post to different accounts. Setting it on the Item or
Item Group saves typing it every time - see
[CGM Shipping Settings](settings.md#allow-any-account-as-item-default).

**It can be corrected after the request is submitted.** The Journal Entry reads the
account off the line when Finance creates it, which can be days later, so a wrong
account no longer means cancelling and re-raising the request. Changing it affects
the **next** entry created from that line; entries already submitted keep the
account they posted to, and correcting those is a Journal Entry matter, not a
Material Request one.

### Columns on the items table

An Operational Expense request shows **Item Code, Quantity, UOM, Currency, Rate,
Amount, Expense Account** and **Required By**. A Purchase request shows the
standard set with Warehouse instead of Currency and Expense Account, because a
Purchase Order in this flow is always raised in the company currency.

That is the default, not a fixed list. Use the gear at the right of the table to
add or remove columns, and your layout is kept for you from then on. **Reset to
default** in the same dialog brings the list above back.

:::note
This grid is driven by code rather than by *In List View* on the DocType. A column
added through Customize Form will not appear here until it is added to the layout
in `public/js/material_request.js`. The gear icon is the supported way to change
what you personally see.
:::

### What the approver sees

Both figures, on both documents.

The Funding Request Totals tab has two parts:

**Totals by Currency** - a table with one row per currency asked for, each showing
Requested, Approved, Disbursed and Outstanding **in that currency**, plus what the
approved figure is worth in company currency. A KES figure is never added to a USD
one.

**Overall Total (Company Currency)** - the same four figures converted and summed
into one number.

| Where | Company currency | Request currency |
|-------|------------------|------------------|
| Material Request | **Total (Company Currency)** | **Totals by Currency**, one line per currency |
| Funding Request | **Overall Total (Company Currency)** section | **Totals by Currency** table |
| Funding Request banner | The blue totals line | A second line, *Requested by currency* |
| Funding Request row | **Requested (Company Currency)** and its approved and disbursed twins | **Requested Amount** and its twins, in the row's own currency |

The overall total is company currency by design. Approval, payment capping and
Outstanding are all decided on one comparable number, which is why a mixed request
still adds up to a single figure an approver can sign against.

A request entirely in the company currency shows no Totals by Currency table, since
one row repeating the overall total below it would be noise.

**A request may mix currencies.** One holding both KES and USD lines becomes **two
Funding Request rows**, one per currency, and later two Journal Entries. It cannot
be paid as one thing: an entry takes money out of a single bank account held in a
single currency. Each row is approved on its own and paid from the account that
matches it, and the Material Request is only marked Disbursed once both are.

### Disbursing

The first entry in **Actions** on an approved Funding Request is the payment step.
It is a standard workflow action, and it is named after what the request is
waiting on, so the menu always says what is pending:

| The action reads | When | What it does |
|------------------|------|--------------|
| **Disburse** | An Operational Expense row has no Journal Entry yet | Creates and submits the entries (and raises any Purchase Orders still needed) |
| **Create Purchase Order** | Only Purchase rows still need their order | Creates the draft orders |
| **Submit Journal Entry** | A draft Journal Entry is waiting | Submits it |
| **Submit Purchase Order** | The order exists but is still a draft | Opens the Purchase Order |
| **Record Purchase Payment** | The order is submitted but not yet paid | Opens the Purchase Order |

The same wording is shown on the request in **Next Step**. The last two are done on
the Purchase Order itself, so the action takes you there and leaves the request as
it is.

Whichever of the first three it reads, it moves every approved row still
outstanding to its payment document:

| Row type | What Disburse does | When the row counts as paid |
|----------|--------------------|-----------------------------|
| **Operational Expense** | Creates a Journal Entry and submits it | Straight away |
| **Purchase / Subcontracting** | Creates a draft Purchase Order | When the supplier's invoice is paid |

1. Choose the account each payment leaves, one per currency. This step is skipped
   when the request has no Operational Expense row.
2. Read the confirmation. It lists every Journal Entry and Purchase Order about to
   be created, and nothing exists yet. The request and document numbers are links
   that open in a new tab.
3. Confirm.
4. The message that follows lists what was created, with a button to open it.

A request with only Operational Expense rows ends in **Disbursed**. One with
Purchase rows goes to **Disbursement in Progress** and moves to Disbursed when the
Purchase Orders are paid.

Things to know:

- **Submitting is final.** A submitted Journal Entry is in the ledger. To reverse a
  payment, cancel the entry; the request then goes back to showing it unpaid.
- **It is all or nothing.** If any document cannot be created or posted, none are,
  and the request is left as it was.
- **A draft raised earlier is posted, not duplicated.** A row that already has a
  draft Journal Entry is listed with that draft, and Disburse submits it as it
  stands.
- **A Purchase Order raised earlier is adopted, not raised again.** If a row's
  order already exists, for example one made straight from the Material Request,
  it is linked to this Funding Request when the request is approved. The request
  goes straight to Disbursement in Progress and the action reads Submit Purchase
  Order.
- **Permissions.** Operational Expense rows need permission to submit Journal
  Entries; Purchase rows need permission to create Purchase Orders.
- **Disbursed is the last state.** There is no separate Complete step: a request
  is finished when it is paid.
- **If a payment is undone,** for example its Journal Entry is cancelled, the request
  goes back to Approved (or Partially Approved) and can be disbursed again.
- **A request is Disbursed when every row is paid in its own currency.** The
  company-currency totals can differ by a few shillings when the rate moved between
  approval and payment; that is an exchange difference, not an amount still owed,
  and Outstanding shows zero.

### Cancelling a Funding Request

**Actions > Cancel Request** is offered on an approved request at every stage,
including Disbursed. It takes the request's payment documents with it:

| The document is | What happens to it |
|-----------------|--------------------|
| A **draft** Journal Entry or Purchase Order | Deleted |
| A **submitted** Journal Entry | Cancelled, which reverses its ledger postings |
| A **submitted** Purchase Order | Cancelled, which hands the ordered quantity back |

The confirmation lists every document and what will happen to it before anything is
touched. Afterwards:

- The Material Requests are released and can be put on a new Funding Request.
- A cancelled entry or order keeps its link to the Funding Request, as the record
  of what was undone, but no longer points at the Material Request.
- The request shows nothing paid.

It is all or nothing. A Journal Entry in a closed period, or a Purchase Order that
already has a receipt or an invoice, cannot be cancelled; the cancel stops there and
nothing is changed.

**A Purchase Order that has been paid stops the cancel.** The message names the
payment. Cancel that payment first, then cancel the request. A Journal Entry is
reversed by its own cancellation, but a payment to a supplier is not, so it has to
be dealt with on the payment itself. You need permission to cancel the submitted documents
themselves.

Only documents tied to this Funding Request are touched. A Purchase Order raised
straight from the Material Request and never taken up by this request is left
alone.

### What the Material Request shows

A Material Request mirrors the row it has on its Funding Request:

| Material Request status | Means |
|-------------------------|-------|
| **On Funding Request** | On a request that is not approved yet |
| **Approved** | Approved, and nothing has been raised for it yet |
| **Disbursement in Progress** | Its Journal Entry or Purchase Order is raised but not yet paid |
| **Disbursed** | Paid in full |

The status follows the request's own row, not the batch: one request on a Funding
Request can be Disbursed while another is still Approved.

### When a Purchase row counts as paid

A Purchase row is paid by payments recorded against its Purchase Order: either
against the supplier's invoice, or as an advance against the order itself before
any invoice exists. Both count, and the request moves to Disbursed once the order
is paid in full.

### What reaches the ledger

When Finance disburses they are asked which bank account the money
leaves, one per currency on the request. The account must be held in either the
request currency or the company currency, and only Bank and Cash accounts are
offered.

The rate is fetched fresh at that moment, not taken from the request:

1. The provider configured in **Currency Exchange Settings** - the most current
   figure available.
2. Failing that, the newest **Currency Exchange** record on or before the posting
   date.
3. Failing that, the estimate typed on the request, which is named in the entry's
   remark so nobody has to guess which rate a posted entry used.
4. Failing all three, the entry is refused rather than posted at a zero rate.

This is the opposite of ERPNext's own order, which reads stored records first.
With **Allow Stale Exchange Rates** switched on - as it is here - a single
Currency Exchange record entered once would otherwise price every payment made
after it, for good.

The entry is a draft. Nothing is paid until Finance submits it, and the rate, the
date and the bank account can all still be changed before they do.

:::tip
A rate that moves between approval and payment shows up as a real difference
between the approved and disbursed company-currency figures. That is accurate, not
an error. A row is closed on the amount in its own currency, so a rate movement
cannot leave a fully paid request looking short.
:::

## 5. Features - guards and settings

| Guard / setting | Effect |
|-----------------|--------|
| Operational Expense without Employee | Save/submit blocked until Employee is set |
| PO before funding approved | Blocked for Purchase / Subcontracting |
| Default Operational Expense Account | JE lines for ops expense; set in **CGM Shipping Settings** |
| Project on MR | Carried into JE / buying documents for shipment costing |
| Shipping Line supplier on PO | Blocked |
| Multicurrency on a non-Operational request | Not offered; lines are forced back to the company currency |
| Multicurrency unticked on an Operational request | Every line forced back to the company currency on save |
| Material Request with two currencies | Split into one Funding Request row per currency |
| Same request and currency twice on one Funding Request | Blocked as a duplicate |
| Bank account in an unrelated currency | Blocked when creating the Journal Entry |
| No exchange rate from any source | Journal Entry refused rather than posted at zero |
| Allow Any Account as Item Default | Offers every account on an Item or Item Group default, groups and disabled excluded; on by default |

### Who approves

The **Funding Approver** role, and never the person who raised the request. The
approver role is read from the workflow, so a site that routes approval through a
different role gets that one.

If you try to approve your own request the block names the role that is waiting,
so you know what to chase rather than being told to "ask another approver". It
names the role and not the people: a refusal message is the wrong place to publish
who holds a finance role, and any such list goes stale as soon as somebody joins or
leaves. Who currently holds it is a question for the role list.

If nobody besides you holds the role, the message says so, because the request is
then stuck until somebody is given it.

Worth checking on your own site: if the same people hold both **Finance User** and
**Funding Approver**, then raising and approving are only kept apart by this
per-document check rather than by the roles themselves. That is a reasonable
arrangement for a small team, but it means the role list alone will not tell an
auditor who can do what.

### What the status on a Material Request means

| Status | Means |
|--------|-------|
| **Draft** | Not submitted yet |
| **Awaiting Funding** | Submitted and waiting to be picked up on a Funding Request |
| **Unfunded** | An Operational Expense request submitted but not yet on a Funding Request |
| **On Funding Request** | Sitting on a Funding Request that has not been approved |
| **Approved** / **Partially Approved** | The approver has decided; payment has not started |
| **Disbursed** | Every currency on the request has been paid |
| **Rejected** | The approver turned it down |

**Awaiting Funding** was called *Submitted* until October 2026. It was renamed
because every submitted document in Frappe is submitted, so the word said nothing
about what the request was waiting for or who was holding it. Existing requests
were moved by a patch, and the app accepts either name so a site that has not
upgraded still works.

Workflow states on Material Request and Funding Request are site-configured ERPNext Workflows; CGM maps pending / approved / disbursed behaviour in code so Desk and reports stay consistent.

## 6. Features - vs clearance task payments

| | Task payments | Funding Request |
|--|---------------|-----------------|
| **Trigger** | Application / permit task on a shipment | Material Request |
| **Examples** | UCR, Permit, Shipping Line, ENTRY_SLIP, KPA | Petty cash, tools, subcontract services |
| **Objects** | Task finance lines → JE / Payment Entry | Funding Request → JE or PO |
| **Guide** | [Finance](finance.md) | This page |

## 7. Related Topics

- [Finance](finance.md) - two finance paths overview
- [CGM Shipping Settings](settings.md#container--port-settings) - Default Operational Expense Account, Allow Any Account as Item Default
- [Operations](operations.md)
- [Getting Started](process-overview.md)
