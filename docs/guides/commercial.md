# Commercial Guide

For **sales** and **pricing** teams: quotations, local charges, customs estimates, and billing.

---

## Where to work

| Item | Path in Desk |
|------|----------------|
| Quotations | **Quotation** (link to Project via `custom_shipment`) |
| Item pricing setup | **Item** → Item Pricing Rules |
| Sales orders | **Sales Order** (from approved quotation) |
| Sales invoices | **Sales Invoice** |
| Print | Quotation / SI → **Print** → CGM formats |

---

## Quotation structure

A CGM quotation has four cost layers:

| Section | Child table / field | Currency |
|---------|---------------------|----------|
| **Import valuation** | Import Cost Component | Transaction + company (KES) |
| **Customs taxes (estimate)** | Customs Tax Component | Company currency |
| **Item pricing** | Quotation Item Pricing | Per rules |
| **Local charges** | Items (standard ERPNext lines) | Quotation currency |

### Shipment reference fields

Typical fields on Quotation:

- HS Code, commodity, weight, container type/qty
- Port of loading / discharge
- Shipment / Project link
- Incoterm, shipment type

---

## Quotation workflow

**Workflow:** `CGM Quotation Approval`

| Step | Action |
|------|--------|
| 1 | Build quotation (valuation + taxes + local charges) |
| 2 | **Submit for Finance Approval** |
| 3 | Finance approves or rejects |
| 4 | Optionally **Share with Client** |
| 5 | Create **Sales Order** or **Sales Invoice** |

Only **Approved** or **Shared with Client** quotations can be billed.

---

## Print formats

| Format | Use when |
|--------|----------|
| **CGM Quotation Full** | Client wants full breakdown (valuation + taxes + local charges) |
| **CGM Quotation Local Charges** | Agency fees only (no customs valuation section) |
| **CGM Quotation Shipping** | Legacy combined layout |

All include QR code for verification. PDF uses Chrome renderer (Frappe 16).

---

## Sales Order / Sales Invoice from quotation

Standard ERPNext **Get Items From → Quotation** is overridden to copy CGM custom fields:

- Shipment references, IDF, ports, refs
- Pricing context

**Sales Invoice** additionally requires:

1. Quotation in billable workflow state
2. **CGM Sales Invoice Approval** workflow → Finance **Approved** before submit

### Sales Invoice print

**CGM Sales Invoice Default** - branded layout with consignee, shipment bar, terms, QR, totals.

---

## Item pricing rules

Configure on **Item** master → **Item Pricing Rules** child table.

Rules can vary by:

- Shipment type
- Container type / size
- Quantity band

Validation prevents overlapping rules on the same item.

At quotation time, **Quotation Item Pricing** rows can be populated from matching rules.

---

## Customs tax estimates

Default tax types (VAT, IDF, RDL, etc.) are seeded in **Customs Tax Type**.

Default rates live in **CGM Shipping Settings → Default Customs Tax**.

Taxes recalculate on quotation save based on customs value (`custom_base_customs_value`).

---

## Typical commercial flow

```
Opportunity (approved) → Project created
  → Quotation linked to Project
    → Finance approves quotation
      → Share PDF with client (Full or Local Charges format)
        → Client accepts
          → Sales Invoice
            → Finance approves SI
              → Submit & collect payment
```

---

## Related guides

- [Finance](finance.md)
- [CRM & Intake](crm-intake.md)
- [Operations](operations.md)
