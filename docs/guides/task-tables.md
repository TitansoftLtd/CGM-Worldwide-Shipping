# The Tables on a Task

Most of the work on a shipment is done by filling in one of four tables on a Task.
This is a column-by-column reference for all four, using the names printed on the
form rather than the field names underneath.

Which tables appear depends on what the task is for. A permit task shows
**Permits (this task)**; a finance payment task shows **Invoices & Receipts**; a
document checkpoint shows **Task Documents**; a transport step shows **Container
Updates**.

| Table on screen | Holds |
|-----------------|-------|
| [Task Documents](#task-documents) | Documents the step needs, draft and final |
| [Invoices & Receipts](#invoices--receipts) | Supplier invoices, payment proofs and receipts |
| [Permits (this task)](#permits-this-task) | One row per permit being applied for or paid |
| [Container Updates](#container-updates) | Per-container dates for transport steps |

---

## How all four behave

**Attachments save the task themselves.** Attaching a file writes the record
immediately. There is no need to press Save afterwards, and no risk of losing the
file by navigating away.

**Greyed-out columns are not broken.** A column is read-only when the tick belongs
to somebody else. Finance owns verification ticks; the declarant owns the uploads.
If a column you expect to use is grey, it is usually because the action sits with
another role. [CGM Shipping Settings](settings.md#document-responsibilities) holds
that mapping.

**Rows drive completion.** These tables are what the completion gates read. When a
task refuses to complete, the dialog names the exact row and column it is waiting
for.

**Add Row adds work, it does not remove it.** Deleting a row that already carries
an attachment removes the evidence, not the obligation.

---

## Task Documents

Also labelled **Clearance Documents** on some steps. One row per document the step
requires.

| Column | Who fills it | Means |
|--------|--------------|-------|
| **Document Type** | Whoever adds the row | Which document this is, for example *CI*, *PKL*, *IDF CERT*, *DO* |
| **Draft Documents** | Ops / Declaration | The working copy, before the final is issued |
| **Final Document** | Ops / Declaration | The issued version. This is the one the gates look for |
| **Status** | Ops | Where the document has got to |
| **Final Document Status** | System | *Draft*, *Pending Review*, *Approved* or *Rejected* - set by the review flow, not typed |
| **Verified By** / **Verified On** | System | Stamped when the document is verified |
| **Uploaded on** / **Uploaded By** | System | Stamped on upload, for draft and final separately |

Rows are often seeded for you from the task template, which is why a row can exist
with nothing attached. An empty required row blocks completion, so either attach
the document or delete the row if it genuinely does not apply.

Final documents can be sent for review. See
[Operations](operations.md#final-document-review).

---

## Invoices & Receipts

One row per invoice, proof of payment or receipt on a finance task. Rows for the
same fee are copied between the application task and its paired finance task, so
the declarant and Finance are looking at the same evidence.

| Column | Who fills it | Means |
|--------|--------------|-------|
| **Item** | System | What the row is, for example *UCR Invoice*. An amended invoice reads *UCR Invoice (Amendment)* |
| **Amendment** | Whoever adds the row | Tick when this invoice replaces an earlier one. The original stays as the audit trail |
| **Purchase Item** | Finance | The item the cost posts against |
| **Attachment** | Depends on the row | The invoice, POP or receipt file |
| **Verified by Finance** | Finance only | Finance has checked the amount before it is paid |
| **Journal Entry** | System | The entry raised by **Make Payment**. Read-only, follow the link to open it |
| **Client will pay** | Finance only | This fee is the client's to settle, so no company Journal Entry |
| **Client Reported Paid** | System | Set when the client confirms payment on the portal |

Three things that commonly confuse people:

- **Only a submitted Journal Entry counts as payment.** A draft posts nothing to
  the ledger, so it neither settles the invoice nor lets the task complete.
- **Client will pay is per row, not only per task.** One invoice on a task can be
  the client's while another is the company's.
- **Verified by Finance is read-only to everyone else**, including the person who
  attached the invoice. That is the control, not a fault.

See [Finance](finance.md) for the full payment flow.

---

## Permits (this task)

One row per permit. The same table appears on the declarant's application task and
on the paired **Finance pays** task, and rows are kept in step between them.

| Column | Who fills it | Means |
|--------|--------------|-------|
| **Permit Type** | Declarant | Which permit, for example *DVS*, *NBA*, *VMD*, *KEPHIS* |
| **Origin** | Declarant | *Local* or *Foreign*. Foreign permits carry no invoice, so only the certificate closes them |
| **Amendment** | Declarant | This permit replaces an earlier application |
| **Permit Invoice (for Finance)** | Declarant | The invoice Finance will pay. Local permits only |
| **Permit Certificate** | Declarant | The issued permit. This is what closes the application task |
| **Journal Entry** | System | The entry Finance raised for this permit |
| **Payment Receipt** | Declarant | The receipt, usually downloaded from the issuing body's portal |
| **Receipt Verified** | Finance only | Finance's own record. It does **not** gate the declarant's task |
| **Uploaded On** / **Uploaded By** | System | Stamped for invoice and certificate separately |

What the application task waits for:

1. Every **Permit Invoice** attached, and verified by Finance
2. Every **Payment Receipt** attached - attached is enough, the tick is not required
3. Every **Permit Certificate** attached

The receipt deliberately needs only to exist. Declarants collect receipts from a
third-party portal and cannot force one to be issued, so requiring Finance's tick
as well used to leave the task stranded behind a Finance task that had already
closed.

See [Declaration & Customs](declaration-customs.md) for the permit flow.

---

## Container Updates

One row per container on a transport step. These rows mirror the Container Tracker.

The important thing to know is that **transport tasks are not completed by hand.**
The Container Tracker drives them: the task marks itself Completed once *every*
container on the project has the step's field filled. One container missing a date
holds the whole step.

| Step | The tracker field that closes it |
|------|----------------------------------|
| Book trucks | **Truck Number** |
| Gate out | **Gate Out Mombasa** |
| Monitor delivery | **Gate In Date (Clearance Station / Warehouse)** |
| Offload | **Offloading Date** |
| Return empty | **Actual Empty Return** |
| Receive interchange | **Interchange Date** *and* **Interchange Document** |

When one of these tasks will not complete, the dialog names the containers still
missing their details. Fill them on the Container Tracker and the task closes
itself. There is a manual fallback - a document, a **Reference No** or a note in
**Description** - but on a project with a tracker, the tracker is the route.

See [Transport & Containers](transport-containers.md).

---

## When a task will not complete

The dialog tells you which table and which row. It is worth reading rather than
dismissing: every one of them names the exact thing outstanding and where to put
it. If it names a field you cannot edit, that action belongs to another role, and
[CGM Shipping Settings](settings.md#document-responsibilities) says whose.

---

## Related guides

- [CGM Shipping Settings](settings.md) - who owns which action, and which documents gate which status
- [Operations](operations.md) - task plans, departments, final document review
- [Finance](finance.md) - payments, receipts and client-pays
- [Declaration & Customs](declaration-customs.md) - permits, UCR, entry
- [Transport & Containers](transport-containers.md) - the Container Tracker
