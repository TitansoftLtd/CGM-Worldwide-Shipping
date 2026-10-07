# CGM Shipping Settings

One Single DocType holds the configuration the whole app reads at runtime: who may
do what, which documents a shipment waits for, which payments wait for a receipt,
and the accounts money lands in. Change a row here and the behaviour changes on
every shipment immediately. No code deployment is involved.

**Where:** search **CGM Shipping Settings** in the awesome bar, or
`/app/cgm-shipping-settings`.

**Who:** System Manager. Treat it as production configuration, because that is
what it is.

---

## At a glance

| Tab | What it decides |
|-----|-----------------|
| [Quotation customs](#quotation-customs) | Default tax rates offered on a quotation |
| [Shipment status documents](#shipment-status-documents) | Which documents a shipment needs before it may move to a status |
| [Finance receipts](#finance-receipts) | Which payment kinds wait for a receipt before the task closes |
| [Roles](#roles) | Who may open which department's tasks, and who owns each document action |
| [Container tracking](#container-tracking-legacy-seq-map) | Which task sequence number maps to which container step |
| [General](#general) | Default company, and when the Packages table appears |
| [Container & Port Settings](#container--port-settings) | KPA day rate and the accounts charges accrue to |
| [Notification Settings](#notification-settings) | Portal URL, deposit refund reminders, and which Notification fires on which event |

---

## Reading the child tables

Five of these tabs are driven by child tables rather than single fields. They all
behave the same way: **each row is a rule**, and the app looks for a row matching
the situation in front of it. No matching row means the rule does not apply, which
is usually permissive rather than blocking, so an empty table is rarely safe to
assume is "off".

Add a row with **Add Row** at the foot of the table, fill every required column,
then **Save** the Settings document. Nothing takes effect until the save.

Delete a row only when you intend the rule to stop applying to every shipment,
including ones already in flight.

---

## Quotation customs

### Default Customs Taxes

Seeds the tax lines offered when a quotation is costed, so the same duty rates do
not have to be typed each time.

| Column | Means |
|--------|-------|
| **Tax Type** (required) | The Customs Tax Type master this default belongs to |
| **Default Rate / Amount** | The figure proposed on a new quotation; the preparer can still override it |

These are defaults, not limits. Changing one does not reprice quotations that
already exist.

---

## Shipment status documents

### Workflow stage requirements

Decides what a shipment must have on file before it may advance. This is the table
behind "the Project will not move to the next status".

| Column | Means |
|--------|-------|
| **Shipment workflow status** (required) | The status being guarded, for example *Documents Received* |
| **Required stage** (required) | The document stage that must be satisfied first, for example *Client documents*, *Pre-IDF*, *IDF & UCR* |
| **Must Be Verified** | When ticked, attaching the document is not enough; it also has to be verified |

A status with no row here is not gated at all. This replaced a hardcoded list, so
adding a requirement is now configuration rather than a code change.

---

## Finance receipts

### Finance receipts

Decides whether a payment task waits for a receipt before it may complete. The
invoice, the payment and any POP are unaffected by these rows; only the receipt
is.

| Column | Means |
|--------|-------|
| **Payment Kind** (required) | Which payment this rule covers, for example *UCR*, *KPA*, *Shipping Line* |
| **Receipt required when the company pays** | Hold the task until a receipt is attached on the company-pays path |
| **Receipt required when the client pays** | Hold the task when the client settles the fee directly |

This exists because the receipt is the one document CGM cannot produce itself. A
client who pays their own entry slip often never sends proof back, and a shipping
line does not always issue a receipt for a payment already evidenced by the bank
POP. Both waits used to be hardcoded, so a finished payment sat Open while someone
chased a third party.

See [Finance](finance.md) for how this interacts with the rest of the payment flow.

---

## Roles

Two different things live on this tab. Both matter and they are easy to confuse.

### Department role lists

Six **Table MultiSelect** fields, one per department: **Finance**, **Operations**,
**Documentation**, **Declaration**, **Transport**, **Field Operations**. Each lists
the roles whose holders may open that department's sea tasks.

| Field | Typical holders |
|-------|-----------------|
| Finance roles | Finance User, Accounts User |
| Operations roles | Operations Manager |
| Documentation roles | CGM Documentation |
| Declaration roles | Declarant |
| Transport roles | Transport staff who book trucks, gate out, deliver, return empties |
| Field Operations roles | Clearance, stuffing and gate processes |

**Finance Department** (a Link to Department) is separate: tasks in that department
are the ones that show the **Make Payment** action.

Keep these lists tight. They are read in more places than task visibility, so a
role added casually here gains more than is obvious. **Operations roles** in
particular also decides who is notified for final document review, so a broad list
emails a lot of people who are not reviewers.

### Document responsibilities

Says who owns each action in each money flow. This is the table that answers "why
can this person not upload the invoice".

| Column | Means |
|--------|-------|
| **Workflow** (required) | *Permit*, *UCR*, *Entry Slip*, *Shipping Line*, *KPA*, *CFS* |
| **Action** (required) | *Upload Invoice*, *Verify Invoice*, *Upload POP*, *Upload Receipt*, *Upload Certificate*, *Make Payment*, *Confirm Client Paid*, *Upload Document* |
| **Role Group** (required) | The CGM Role Group that may perform it, for example *Declaration* or *Finance* |
| **Notes** | Free text, for whoever reads the row next |

A user qualifies if they hold a role in the group **or** sit in its department.
Administrator bypasses every check here, so testing a permission change as
Administrator proves nothing. Log in as a real holder of the role instead.

With no row for a flow and action, the app falls back to Finance for the money
actions (verify, receipt, POP, payment, confirm client paid) and Declaration for
everything else.

### Notification email templates

Three **Code** fields holding the HTML for the default, permit-finance and
UCR-finance notification emails.

---

## Container tracking (legacy seq map)

Maps each container step to the task sequence number that represents it: ETA
Refresh, Vessel Arrival, Field Clearance, KPA Paid, Book Trucks, Gate Out, Monitor
Delivery, Offload, Empty Return, Interchange.

These numbers are how the Container Tracker knows which task to complete when every
container has its date filled. Changing one re-points a step at a different task,
so leave them alone unless a task plan's numbering has genuinely changed.

**Default KPA Free Days** seeds new Container Tracker records.

---

## General

**Default Company** is used to resolve the department suffix when tasks are created.

**Package field visibility** holds two Table MultiSelect fields, **Show packages for
Mode of Transport** and **Show packages for Cargo Type**, which decide when the
Packages table appears on a shipment. Air and LCL consignments need it; a full
container generally does not.

---

## Container & Port Settings

| Group | Fields |
|-------|--------|
| KPA Port Chargeable Days | **KPA Port Daily Rate**, **KPA Port Rate Currency** |
| Container Charge Accrual Accounts | **Demurrage Expense**, **Demurrage Accrued Payable**, **KPA Port Expense**, **KPA Port Accrued Payable** |
| Funding | **Default Operational Expense Account** |

The accrual accounts are where container charges post. Getting one wrong misstates
the ledger rather than breaking the workflow, which makes it harder to notice, so
change these with Finance present.

---

## Notification Settings

**Client Portal URL** and **Operations Notification Email** are the addresses used
in outbound messages.

### Container deposits

**Container Deposit Account** is the asset account debited when Finance pays a
deposit. **Container Deposit Sales Item** is the item used on the Sales Invoice
line for the deposit.

The reminder schedule governs chasing the refund after a container is returned:
**Remind After** and its unit set the first reminder, **Repeat Every** and its unit
set the cadence, and **Stop After (days)** caps how long reminders continue.
Reminders stop early once the refund is recorded.

### Workflow notifications

Binds a Notification record to a workflow event, so the message can be changed or
switched off without touching code.

| Column | Means |
|--------|-------|
| **Workflow Event** (required) | The moment that fires it, for example *Finance Payment Action* or *Permit Invoices to Finance* |
| **Notification** (required) | The Notification record to send |
| **Notes** | Free text |

Remove the row and that event stops notifying. The underlying action still happens.

---

## Changing settings safely

1. **Check who is affected first.** These rules apply to shipments already in
   flight, not only new ones. Tightening a gate can stop work mid-stream.
2. **Save before testing.** Nothing takes effect until the Settings document is
   saved.
3. **Do not test as Administrator.** Administrator bypasses every responsibility
   check, so a permission change will appear to work when it does not.
4. **Prefer narrowing a role list to editing code.** Most "too many people are
   involved" problems are a role list that grew, not a defect.

---

## Related guides

- [What CGM Adds to ERPNext](customizations.md) - the full DocType and field inventory
- [Finance](finance.md) - how the receipt rules and responsibilities play out in payment tasks
- [Operations](operations.md) - task plans, departments and final document review
- [Declaration & Customs](declaration-customs.md) - permits, UCR and entry flows
