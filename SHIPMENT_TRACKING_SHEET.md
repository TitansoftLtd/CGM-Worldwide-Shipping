# Shipment Tracking Sheet ↔ Project

Maps the **operations LCL tracking spreadsheet** to the **Project** form (first section).

## Visual workflow on Project

At the top of every clearance **Project**, the **Clearance Progress** bar shows:

- All **workflow states** (Draft → Completed)
- **Current status** (highlighted)
- **Sea task progress** (e.g. 2/24 completed)

## Field mapping (spreadsheet → Project)

| Spreadsheet column | Project field | When to fill |
|-------------------|---------------|--------------|
| **DATE** | `custom_opened_date` | When file is opened |
| **CONSIGNEE** | `custom_consignee` | At creation (from Lead/Customer) |
| **CGM REF NO** | `custom_cgm_ref_no` / `project_name` | e.g. `CGM/LCL001/1022` |
| **AWB/BL** | `custom_bl_number` (sea) / `custom_awb_number` (air) | When known |
| **CLIENT REF** | `custom_client_ref_no` | Client’s reference |
| **ENTRY NO** | `custom_entry_no` | After entry lodged |
| **WEIGHT** | `custom_weight_nw`, `custom_weight_gw`, `custom_weight_notes` | From CI/PKL |
| **ETA** | `custom_eta` | Expected arrival |
| **SHIPPING LINE CHARGES** | `custom_shipping_line_charges_note` | Text (e.g. USD paid by client) |
| **PORT/CFS CHARGES** | `custom_port_cfs_charges_note` | Text (storage, CFS fees) |
| **KEBS CHARGES** | `custom_kebs_charges` (+ notes in `custom_charge_notes`) | Amount / narrative |
| **KPA/CFS CODE** | `custom_cfs_code` (FFK, MCT, SIG, …) | Port/CFS code |
| **STATUS** | `custom_shipment_status` | Workflow (read-only badge) |
| **DATE SETTLED** | `custom_date_settled` | When file closed |
| **AGENT ALLOCATION** | `custom_agent_allocated` | Employee link |
| **COMMENTS** | `custom_shipment_remarks` | Ops notes |
| **IDF NO** | `custom_idf_number` | After IDF/UCR step |

Also on Project:

- **Shipment Type** — Sea LCL, Sea FCL, Air Import, …
- **Mode of Transport** — Sea / Air / Road
- **Client Documents** — CI, PKL, KRA PIN (from CRM)
- **Regulatory Permits** — DVS, NBA, VMD, ACA
- **Linked records** — IDF UCR Record, Customs Entry, containers, KPA, line charges

## Initiation (minimum at project create)

When creating a Project from Customer/Lead:

1. **Date (Opened)**, **Consignee**, **CGM Ref**, **Shipment Type**, **Mode**
2. **Client Ref**, **B/L** (or AWB)
3. **Shipment Status** = usually **Documents Received** if CI/PKL came from CRM
4. **Client Documents** populated automatically
5. **Sea Task Plan** auto-created; tasks **1–2** auto-completed with documents

## Process alignment

```text
[CRM: CI/PKL approved]
        ↓
[Project: Tracking sheet fields + workflow chart]
        ↓
[Tasks 1–2 auto-done] → [Task 3 UCR] → … → [Completed]
```

See [SEA_FREIGHT_PROCESS.md](SEA_FREIGHT_PROCESS.md) for the full 24-task chart.

For **FCL / container** shipments (Mombasa CNT, ICD, transit), see [CONTAINER_TRACKING_FLOW.md](CONTAINER_TRACKING_FLOW.md) — **ATA** and gate/warehouse dates are captured **per container** after the vessel berths, not at LCL project open.

## Apply layout on site

```bash
bench --site cgm.local migrate
bench --site cgm.local clear-cache
```

Then hard-refresh the browser when opening a **Project**.
