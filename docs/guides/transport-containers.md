# Transport & Containers Guide

For **transport coordinators** and **operations** managing containers, demurrage, and transporter assignments.

---

## Where to work

| Item | Path in Desk |
|------|----------------|
| Container records | **Container Tracker** |
| Live dashboard | **Container Ops Board** |
| Transporter jobs | **Container Allocation** |
| Empty interchange | **Interchange Receipt** |
| Seal tracking | **Seal Record** |
| Reports | Container Tracking Detail, Container Return Tracker |

---

## Container lifecycle

```
Bill of Lading containers
  → Container Tracker (one record per container_number per project)
    → Task Container Updates (on transport tasks 20–25)
      → Daily metrics refresh (demurrage / detention)
        → Container Ops Board
```

### Status progression

| Status | Typical trigger |
|--------|-----------------|
| Pending Arrival | Created, vessel not yet berthed |
| Vessel Berthed | ATA / berth date set |
| Discharged / At Port | Discharge date |
| Released / In Transit | Gate out from port |
| At Warehouse | Arrival at CFS / warehouse |
| Cargo Offloaded | Offload confirmed |
| Empty Returned | Empty container at depot |
| Interchange Received | Interchange receipt filed |
| Return Overdue | Past free days / deadline |

Statuses are **derived from dates** on Container Tracker (daily scheduler recalculates charges).

---

## Sea-import transport tasks (20–25)

| Seq | Task |
|-----|------|
| 20 | Book trucks and notify warehouse |
| 21 | Load trucks and exit port |
| 22 | Monitor delivery to destination |
| 23 | Offload cargo |
| 24 | Return empty container to depot |
| 25 | Receive interchange confirmation |

Use **Task Container Update** child table on these tasks to record per-container gate-out, delivery, offload, and return dates.

---

## Container Ops Board

**Desk:** CGM Shipping → Container Ops Board  
**Route:** `container-ops-board`

Features:

- KPI tiles: overdue returns, demurrage exposure, free days expiring
- Filters: customer, project, B/L, batch, clearance station
- Tabs: **All Containers**, **Empty Return Tracker**
- Column layout: Shipment, Client, B/L, Containers, Batch, etc.

---

## Container Allocation (transporters)

**Container Allocation** assigns containers from a Project/B/L to a **Supplier** (transporter).

- Submittable document
- Child rows: **Container Allocation Item**
- Transporters view assignments at **`/transporter/allocation`**

Transporter suppliers sync portal users on save (`transporter_supplier.py`).

---

## Shipping line charges (Supplier master)

On **Supplier** (shipping line), configure:

| Child table | Purpose |
|-------------|---------|
| Shipping Line Free Days Rule | Free days by destination |
| Shipping Line Demurrage Tier | Demurrage rate tiers |
| Shipping Line Detention Tier | Detention rate tiers |

Used when calculating container charges on Container Tracker.

---

## Interchange Receipt

Submittable confirmation when empty container is returned to depot — links to task 25 completion.

---

## Reports

| Report | Use |
|--------|-----|
| Container Tracking Detail | Full container timeline |
| Container Return Tracker | Empty return focus |
| Container Tracking Report | Summary tracking |

---

## Related guides

- [Operations](operations.md)
- [Portals](portals.md)
- [Finance](finance.md) (shipping line invoice tasks 12–13)
