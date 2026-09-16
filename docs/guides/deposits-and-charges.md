# Container Deposits & Charges Guide

For **Finance** and **Operations** handling container deposits, demurrage and port charges.

Two separate pots of money run alongside a shipment:

- the **container deposit** - a refundable hold the shipping line takes against the boxes, and
- **container charges** - demurrage, detention and KPA port storage that build up while the boxes are out.

This guide covers both, and the overnight jobs that keep them moving.

---

## Part 1 - Container deposits

### Where a deposit starts

On the **Bill of Lading**, in the **FCL / Containers** section:

| Field | What it means |
|-------|---------------|
| **Deposit Arrangement** | **Container Deposit** (the line holds a deposit) or **Revolving Fund** (a standing float, no per-shipment deposit). Leave blank when there is no deposit. LCL shipments do not show it. |
| **Deposit Currency** | Defaults to USD when you pick Container Deposit. |
| **Deposit Amount** (per container row) | What the line holds for that box. The Bill of Lading totals them. |
| **Deposit Paid By** | Read-only here. Finance sets it from the task (below). |

Everything else on the deposit follows from those.

### Who pays it

On the **Finance pays Shipping Line Charges** task, Finance picks one of three buttons under **Actions**, and only while the payer is still blank:

- **Deposit paid by Agent** - the agent carries it. No refund tracking, and no invoice to the client.
- **Deposit paid by Customer** - the client funds it, so it is invoiced to them.
- **Deposit paid by Company** - CGM funds it from its own account.

The choice writes back to the Bill of Lading and onto every Shipping Line task on the shipment.

### Paying the deposit

**Make Payment** on that task is for the **shipping line charges only**. The deposit is paid separately:

1. **Customer-paid deposits first need an invoice.** Use **Sales Invoice (SL + Deposit)** on the task. It opens an unsaved Sales Invoice with two lines, the shipping line charges and the container deposit. Save and submit it as usual, and it links itself back to the Bill of Lading.
   - This needs a **Container Deposit Sales Item** configured in CGM Shipping Settings.
2. **Company-paid deposits** are invoiced from the Project instead, with **Create Company Deposit Invoice**. It creates a draft Sales Invoice for the deposit alone.
3. **Then record the payment.** **Make Deposit Payment** on the task opens a dialog with the Bill of Lading total, the posting date, a reference, and the two accounts: **Pay To: Container Deposit (Debit)** and **Pay From: Bank/Cash (Credit)**. **Create Journal Entry** makes **one draft entry for the whole Bill of Lading**.
   - The entry is a **draft**. Someone still has to submit it, which you can do from the task with **Submit Journal Entry**.
   - The Pay To account defaults from Settings. If you choose a different one you get a warning, not a block.

The task will not complete until the payer is chosen, the amounts are on the Bill of Lading, the deposit is paid, and (for customer-paid deposits) the Sales Invoice is submitted.

### Getting the deposit back

Refund tracking starts on its own. The moment the **last** container on the Bill of Lading has an **Empty Return** or **Interchange** date, the deposit moves to **Refund Pending** and the return date is stamped.

**Agent-paid deposits are never tracked** - there is nothing for CGM to reclaim.

From the **Project**, Finance then has:

| Button | Use it when |
|--------|-------------|
| **Record Deposit Refund JE** | The line is returning the money. Creates a draft Journal Entry crediting the container deposit account. **Submitting that entry marks the deposit Received.** |
| **Confirm Container Deposit Refund** | The refund is settled and no accounting entry is needed here. Marks it Received straight away. |
| **Create Deposit Credit Note** | The client paid the deposit and is getting it back. Credits the deposit line of the original Sales Invoice. This is the client's side of the refund, and does not by itself change the refund status. |
| **Mark Deposit Forfeited** | The line is keeping the deposit. **Accounts Manager only.** Stops the reminders for good. |

The Project also shows **Deposit Refund Status**, who confirmed it and when, plus deposit badges on each container card.

### Reminders

While a deposit sits at **Refund Pending**, Finance is reminded by email: **"Container deposit refund due - BL …"**. The timings are in CGM Shipping Settings, section **Container deposits**:

- **Remind After** - how long after the containers came back the first reminder goes (default 2 days);
- **Repeat Every** - how often it repeats (default 24 hours);
- **Stop After (days)** - when to give up (default 14 days).

Reminders stop as soon as the refund is recorded, confirmed or forfeited.

### Deposit settings

In CGM Shipping Settings:

- **Container Deposit Account** - the asset account debited when the deposit is paid.
- **Container Deposit Sales Item** - the item used on the deposit line of a Sales Invoice.
- The three reminder settings above.

---

## Part 2 - Container charges

### What is charged

Two charges, computed per container on the **Container Tracker**:

| Charge | Counts from | Stops when |
|--------|-------------|------------|
| **Demurrage/Detention** (one combined charge) | The day after **Shipping Line Free Day End Date** | The container is returned (Empty Return or Interchange), else today |
| **KPA Port** storage | The day after **KPA Free Day End Date** | The box leaves Mombasa port (gate out, offloading, gate in at warehouse, return or interchange), else today |

The tracker also shows **Port Days Used** and **Days Outstanding** (days past the expected empty return). All of these recalculate whenever the tracker is saved, and again overnight.

### Where the rates come from

- **Demurrage/detention:** the **Shipping Line Demurrage Tiers** table on the shipping line's **Supplier** record - a ladder of **From Day**, **To Day**, **Daily Rate** and **Currency** per **Cargo Size**. Charges are summed day by day, so a 1-10 / 11-20 / 21+ ladder bills correctly. A tier with **To Day** = 0 is open ended.
- **KPA port:** **KPA Port Daily Rate** and **KPA Port Rate Currency** in CGM Shipping Settings.
- **Per-container overrides:** a daily rate typed on the tracker beats the tables, and the adjustment fields add or subtract a fixed amount.
- The **Shipping Line Free Days Rules** table on the Supplier is reference only. The **dates on the Container Tracker** are what actually drive the day counts.

### Posting the charges to the ledger

Charges accrue on the tracker as a running figure. Getting them into the accounts is a separate step.

**Post Container Charge Accrual** on the Project posts **only the increase since the last time** as one **submitted** Journal Entry, with a debit and credit pair per charge type and currency, and a breakdown line per container. The entry is remarked "Container charge accrual - <project>".

- It needs the four accrual accounts in CGM Shipping Settings: **Demurrage Expense**, **Demurrage Accrued Payable**, **KPA Port Expense** and **KPA Port Accrued Payable**.
- If a charge is in a currency other than the account's, a **Currency Exchange** record must exist for the day.
- If nothing has grown since last time, it says so and posts nothing.
- Anyone who can edit the Project can post it, and it posts straight to the ledger, so treat it as a finance action.

**Careful:** cancelling an accrual Journal Entry does **not** reset what the trackers think has been posted, so the same amount will not accrue again. Ask for a correcting entry instead of cancelling.

The Project shows **Demurrage/Detention Accrued Total**, **KPA Port Accrued Total** and their **Posted to JE** counterparts, and **View Journal Entries** lists every submitted entry linked to the shipment. Deposits are deliberately left out of the project cost totals: a deposit is a refundable hold, not a cost.

---

## Part 3 - What runs overnight

| Job | How often | What you see |
|-----|-----------|--------------|
| Container metrics refresh | Daily | Open containers' day counts, charge amounts, status and location move on their own. Closed containers stop changing. |
| Container charge accrual | Daily | New submitted Journal Entries on shipments where charges grew, and the Project's posted totals go up. A project that fails (missing account, missing exchange rate) is skipped quietly and written to the Error Log, so check it if a shipment stops accruing. |
| Licence expiry reminders | Daily | Licence statuses and days to expiry refresh, and reminders go out - see [Licence & Permit Register](licences.md). |
| Deposit refund reminders | Hourly | The reminder emails described above. Each Bill of Lading is throttled, so hourly does not mean hourly emails. |

---

## Related guides

- [Transport & Containers](transport-containers.md) - the Container Tracker, ops board and container lifecycle
- [Finance](finance.md) - task payments, invoices and receipts
- [Operations](operations.md) - the clearance task plan
