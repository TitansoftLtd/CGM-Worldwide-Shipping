# Container & Shipment Tracking — ERP Project Flow

**Master record:** ERPNext **Project** (shipment file)  
**Per-container:** **Container Tracker** (one row per container / B/L line)  
**Seals:** **Seal Record** (Mombasa / Nairobi / Malaba)  
**Daily ops:** **Daily Status Update** (per team/group)

---

## Two phases on every sea shipment

```text
┌─────────────────────────────────────────────────────────────────┐
│  PHASE A — BEFORE VESSEL BERTH (Project header)                 │
│  Mombasa CNT / pre-arrival updates                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓ vessel berths (fill ATA)
┌─────────────────────────────────────────────────────────────────┐
│  PHASE B — AFTER VESSEL BERTH (Container Tracker per unit)      │
│  Mombasa port · ICD · Transit · Warehouse · Empty return        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase A — Before berth (Project fields)

Fill on **Project** when the file is opened and while cargo is **in transit to Mombasa**. Do **not** fill ATA or container gate dates here.

| Field | Project field | Required at open? |
|-------|---------------|-------------------|
| Client name | Customer + **Consignee** | Yes |
| Batch No. | `custom_batch_no` | Recommended |
| Quantity | `custom_shipment_quantity` | Recommended |
| Shipping Line | `custom_shipping_line` | When known |
| Vessel | `custom_vessel_flight` | When known |
| E.T.A | `custom_eta` | When known |
| B/L | `custom_bl_number` | When known |
| IDF | `custom_idf_number` | After UCR/IDF tasks |
| Permits | `custom_permit_register` | During pre/post clearance |
| Shipping Line charges | `custom_shipping_line_charges_note` | When invoiced |
| D.O | `custom_do_reference` | When DO lodged |
| Entry & Taxes | `custom_entry_no` + charge notes | After entry lodged |
| Custom Release Date | `custom_custom_release_date` | When customs releases |

**Berth phase indicator:** `custom_berth_phase` = **Before Vessel Berth** until ATA is recorded (system can move to **After Vessel Berthed** when ATA or first container discharge is set).

---

## Phase B — After berth (Container Tracker)

Create one **Container Tracker** per container, linked to the **Project**.

### Core table (all modes)

| # | Field | DocType field |
|---|--------|---------------|
| 1 | Container number | `container_number` |
| 2 | Shipment Id (batch no) | `batch_bl_no` |
| 3 | B/L | `bl_number` |
| 4 | ETA | `eta` |
| 5 | ATA | `ata` |
| 6 | Offloading / Discharging date | `discharging_date` |
| 7 | Custom release date | `custom_release_date` |
| 8 | Gate out date (port) | `gate_out_date_port` |
| 9 | Delivery date | `delivery_date` |
| 10 | Empty return date (actual) | `actual_empty_return` |
| 11 | Gate in date (warehouse / depot) | `gate_in_date_warehouse` / `gate_in_date_depot` |
| 12 | Free days | `free_days` |
| 13 | Demurrage days | `demurrage_days` (auto) |
| 14 | Detention days | `detention_days` (auto) |
| 15 | Status | `status` (auto) |

### Container mode (`container_mode`)

| Mode | Use for |
|------|---------|
| **Mombasa Port** | Discharge at port → gate out → warehouse → empty return |
| **ICD Nairobi** | Mombasa discharge → ICD gate in/out → warehouse |
| **Transit Kenya→Border** | Kenya to outside borders |
| **Transit Border→Kenya** | Outside borders into Kenya |
| **Export** | Export container moves |

Mode-specific dates (ICD gate in/out, border clearance, loading/offloading) are on the same form; the UI highlights relevant fields per mode.

---

## Auto-calculations (Container Tracker)

| Metric | Rule |
|--------|------|
| **Free days (port)** | Contractual free time at port/CFS |
| **Port timeline** | Days from **Discharging** → **Gate out (port)** |
| **Demurrage days** | `max(0, port_days − free_days)` — penalty while container sits in terminal/CFS |
| **Demurrage amount** | `demurrage_days × daily_demurrage_rate` |
| **Demurrage date** | First calendar day demurrage applies (end of free time + 1) |
| **Detention days** | Days from **Gate out (port)** → **Actual empty return** (container out until empty shell returned to depot) |
| **Expected empty return** | `gate_out_date_port + free_days` |
| **Days outstanding** | Days since expected return if not yet returned |
| **Status** | Dispatched → Delivered → Empty Pending → Empty Returned / **Overdue** |

These support: demurrage billing, port compliance, customer billing, and shipment performance analysis.

---

## Seals

**Seal Record** linked to **Project** (and optional **Container**):

| Field | Purpose |
|-------|---------|
| Seal no. | `seal_number` |
| Seal point | Mombasa / Nairobi / Malaba |
| Shipment quantity | `shipment_quantity` |
| Container | `container_tracker` link |

---

## Daily Status Update (centralized)

Each **Group / Team** submits one record per day:

| Field | Purpose |
|-------|---------|
| Shipments dispatched | Count |
| Deliveries completed | Count |
| Delays / issues | Text |
| Empty containers pending | Count |
| Containers returned today | Count |
| Outstanding actions | Text |
| **RAG status** | Green = on track · Yellow = attention · Red = critical |

On **submit**, **Red** (and **Yellow**) triggers email to **Operations Manager** role.

---

## Empty container return module

Implemented on **Container Tracker** (not a separate app):

- Status: Dispatched / Delivered / Empty Pending / Empty Returned / **Overdue**
- Search/filter: Project list, Container Tracker list (customer via Project, status, dates)
- Dashboard: Workspace shortcuts + Project container summary table

---

## Commercial / quotes (roadmap)

See [REQUIREMENTS_ROADMAP.md](REQUIREMENTS_ROADMAP.md) for: Air/LCL/FCL split, auto quotes, duty %, approval workflow, FOB/Ex-works, rate clauses, user access, reports, standard rates.

---

## Apply on site

```bash
cd ~/frappe-bench
bench --site cgm.local migrate
bench --site cgm.local clear-cache
```

Open **Project** → fill **Before Vessel Berth** → after arrival set **ATA** → add **Container Tracker** rows from the container section or workspace.
