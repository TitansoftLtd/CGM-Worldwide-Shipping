---
title: Customer & Transporter Portal
metatags:
  description: Customer portal routes for shipments, documents, quotations, invoices, and messages; transporter allocations and invoices; Desk vs portal; troubleshooting.
---

# Customer & Transporter Portal

**Website access for customers and transporters — progress, documents, and commercial files without Desk.**

Use this guide when onboarding portal users, explaining what customers can see, or diagnosing missing shipments and allocations.

A typical scenario: After Finance shares a quotation and Operations advances the Project, the customer logs into `/portal`, opens **My Shipments**, downloads documents, and replies via **My Messages**. A transporter opens `/transporter/allocation` for assigned containers and `/transporter/invoices` for shared purchase invoices.

Customer home:

> Website → `/portal`

Transporter home:

> Website → `/transporter`

## 1. Prerequisites

### Customer

- **Customer** master
- **Website User** with role **Customer**, linked to that Customer
- Project(s) with matching customer
- Quotations only appear when workflow is **Shared with Client** (and invoices when submitted/visible per portal rules)

### Transporter

- **Supplier** marked as transporter
- Portal user synced (`transporter_supplier` on save)
- Role **Transporter**
- **Container Allocation** submitted for jobs to appear

:::note
Website users are redirected away from Desk to their portal home. Support staff use Desk; customers and transporters use the website.
:::

## 2. How to — Customer portal

| Route | Purpose |
|-------|---------|
| `/portal` | Dashboard home |
| `/my-shipments` | List of customer shipments |
| `/shipment` | Shipment detail / progress |
| `/documents` | Download shared documents |
| `/my-quotations` | Quotations shared with the client |
| `/my-invoices` | Sales invoices |
| `/my-messages` | Shipment Update / messaging threads |
| `/container` | Container Tracker timeline (`?name=…`) |

### What customers see

- Progress aligned with Project shipment status
- Documents operations has made available
- Commercial PDFs when quotation is **Shared with Client**
- Timestamps localized in the browser (`portal_localize_time.js`)

### Desk vs portal

| Action | Where |
|--------|-------|
| Upload / verify clearance documents | Desk (Operations / Documentation) |
| View progress and download shared files | Portal |
| Approve quotation internally | Desk (Finance) |
| View shared quotation / invoice PDF | Portal |
| Reply on shipment messages | Portal (**My Messages**) and Desk (**Shipment Update**) |
| Raise Funding Request / pay Tasks | Desk only |

## 3. How to — Transporter portal

| Route | Purpose |
|-------|---------|
| `/transporter` | Dashboard |
| `/transporter/allocation` | Container allocation jobs |
| `/transporter/invoices` | Purchase invoices shared with the transporter |
| `/transporter/profile` | Profile settings |

Ops share transporter invoices from Desk (Purchase Invoice share flow). Outstanding amounts shown are what CGM still expects the transporter relationship to settle as configured on site.

## 4. Features — Messaging and feedback

- **Shipment Update** threads power portal messages; unread items surface on the portal home and `/my-messages`.
- **Portal Feedback** captures customer feedback for ops follow-up (Desk).

## 5. How to — Troubleshooting

### Customer cannot see a shipment

1. Website User linked to the correct **Customer**.
2. Project **customer** matches that Customer.
3. User has role **Customer** (not only Employee).
4. Soft-check portal API visibility / document sharing if the Project exists but documents are empty.

### Customer cannot see a quotation

1. Quotation party = Customer.
2. Workflow state **Shared with Client** (Approved alone may not publish to portal).

### Transporter cannot see allocation

1. Supplier has transporter flag; portal user linked and active.
2. **Container Allocation** is **submitted**.
3. Allocation points at the correct Project / B/L / containers.

### Transporter cannot see invoices

1. Purchase Invoice was shared to that transporter via the CGM share action.
2. User is the synced transporter Website User for that Supplier.

### Redirect loop or landing on wrong home

1. Roles on the Website User (`role_home_page` / session hooks).
2. Clear cache / re-login after role changes.
3. Confirm Website User roles and Customer/Supplier links on Desk.

## 6. Related Topics

- [CRM & Intake](crm-intake.md)
- [Transport & Containers](transport-containers.md)
- [Commercial](commercial.md)
- [Finance](finance.md)
- [Getting Started](process-overview.md)
