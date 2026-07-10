# Customer & Transporter Portal Guide

For **portal users** and **support staff** helping customers and transporters use the website.

---

## Customer portal

**Role:** `Customer` (Website User linked to Customer master)  
**Home after login:** `/portal`

| Route | Purpose |
|-------|---------|
| `/portal` | Dashboard home |
| `/my-shipments` | List of customer shipments |
| `/shipment` | Shipment detail / progress |
| `/documents` | Download uploaded documents |
| `/my-quotations` | View quotations shared with client |
| `/my-invoices` | View sales invoices |

### What customers see

- Shipment progress aligned with Project workflow status
- Document availability (as shared by operations)
- Commercial documents when quotation is **Shared with Client**
- Timestamps localized to browser timezone (`portal_localize_time.js`)

### Desk vs portal

| Action | Where |
|--------|-------|
| Upload clearance documents | Desk (operations) |
| View progress | Portal |
| Approve quotation internally | Desk (finance) |
| View shared quotation PDF | Portal |

---

## Transporter portal

**Role:** `Transporter`  
**Home after login:** `/transporter`

| Route | Purpose |
|-------|---------|
| `/transporter` | Transporter dashboard |
| `/transporter/allocation` | Container allocation jobs |
| `/transporter/profile` | Profile settings |

Transporter users are synced from **Supplier** records marked as transporters (`transporter_supplier.py`).

---

## Access control

- Website users are redirected from Desk to portal (`before_request` hook).
- `role_home_page` in hooks.py sets default landing per role.
- Session creation hook routes CGM portal users after login.

---

## Supporting portal users

### Customer cannot see shipment

1. Confirm Website User is linked to correct **Customer**.
2. Confirm Project customer matches.
3. Check document sharing / project visibility rules in portal API (`portal.py`).

### Transporter cannot see allocation

1. Confirm Supplier has transporter flag and portal user linked.
2. Confirm **Container Allocation** is submitted.
3. Check allocation references correct Project/B/L.

---

## Related guides

- [CRM & Intake](crm-intake.md)
- [Transport & Containers](transport-containers.md)
- [Commercial](commercial.md)
