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

## How a job reaches a transporter

1. **Shipment details arrive** from Documentation.
2. **Documents go to the transporter** - Bill of Lading, and the Delivery Order or container guarantee.
3. **ETA is shared**, then kept current. Tracking runs daily until KRA releases the cargo, and the transporter is updated as it moves.
4. **Transporter sends truck details**, and the containers are allocated to them.
5. **Loading**, after the containers are verified, then the truck exits the port.
6. **The contact person for the shipment** is passed to the transporter, who passes it to the drivers - so the person on the road can reach someone directly.
7. **Delivery Order / container guarantee reaches the drivers**, because that is what they need to return the container afterwards.
8. **Offload, then return the empty** to the appointed depot.
9. **Interchange issued** at drop-off, and shared back to Tracking or Documentation.

Step 9 is the one that pays: the interchange is the proof the container came back, and it is what the **container deposit refund** is claimed against.

**Trucks are booked before the cargo is released**, not after. Planning overlaps clearance so movement starts the moment the entry is released - which is also why the warehouse is told to make space, and have bags and labour ready, while clearance is still running.

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

Submittable confirmation when empty container is returned to depot - links to task 25 completion.

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
