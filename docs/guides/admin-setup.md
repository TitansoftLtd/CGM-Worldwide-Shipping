# Admin & Setup Guide

For **system administrators** deploying and maintaining CGM Shipping on a Frappe bench.

---

## Installation

```bash
# From bench root
bench get-app <repo-url> cgm_shipping   # if not already present
bench --site <site> install-app cgm_shipping
bench --site <site> migrate
bench restart
```

App hooks: `cgm_shipping/hooks.py`  
Post-migrate: `cgm_shipping/install.py` → `after_migrate`

---

## First-time setup checklist

### 1. Masters

| Master | Action |
|--------|--------|
| **Shipment Type** | Enable sea-import workflow flag for import shipments |
| **Document Type** | Verify codes: CI, PKL, UCR, MANIFEST, DO, etc. |
| **Permit Type** | Link permit types to ERPNext Items |
| **Clearance Station** | Seeded by patch (21 KRA CFS locations); review |
| **CFS Location** | Seeded; link to stations as needed |
| **Customs Tax Type** | Seeded (VAT, IDF, RDL, …) |
| **Container Type / Size** | Align with your operations |
| **Mode of Transport** | Sea, air, etc. |

### 2. CGM Shipping Settings (single doc)

Open **CGM Shipping Settings** and review:

| Child table | Purpose |
|-------------|---------|
| Sea Import Task Template | 25 task subjects + departments |
| Sea Clearance Task Requirements | Completion rules per task seq |
| Sea Workflow Task Gates | Min task seq per `custom_shipment_status` |
| Workflow Stage Requirements | Document verification per workflow state |
| Default Customs Tax | Default rates for quotations |
| Finance Cost Category Map | JE → project cost buckets |
| CGM Role Item | Role groupings |

Patches seed defaults from `sea_settings_seed_data.py` on migrate.

### 3. Workflows

Installed by patches (idempotent):

| Workflow | DocType |
|----------|---------|
| CGM Quotation Approval | Quotation |
| CGM Sales Invoice Approval | Sales Invoice |
| CGM Sea Import Workflow | Project (`custom_shipment_status`) |

Opportunity approval workflow is expected on site (configure in ERPNext if not present).

### 4. Print formats

| Format | DocType |
|--------|---------|
| CGM Quotation Full | Quotation |
| CGM Quotation Local Charges | Quotation |
| CGM Quotation Shipping | Quotation |
| CGM Sales Invoice Default | Sales Invoice |

PDF generator: **Chrome** (requires Google Chrome on server).  
Patches: `ensure_quotation_print_formats`, `switch_quotation_print_formats_to_chrome`, `ensure_sales_invoice_print_format`.

### 5. Roles & permissions

- Map users to ERPNext departments matching task template: Operations, Declaration, Finance, Documentation, Field Operations, Transport.
- Task list is department-scoped (`permissions.py`).
- Finance roles for quotation/SI approval actions.

### 6. Website / portal

- Create Website Users for customers (role Customer).
- Link transporter suppliers and sync portal users.
- Test `/portal` and `/transporter` after `bench restart`.

---

## Patches overview

All patches in `cgm_shipping/patches.txt` run on `bench migrate`.

| Category | Examples |
|----------|----------|
| Seed data | Task template, requirements, gates, stations, tax types |
| Workflows | Quotation, SI, entry/shipping-line/permit/KPA finance |
| Schema | Supplier shipping line tables, container updates, quotation pricing |
| Print formats | Quotation + SI HTML templates |
| Workspace | Container Ops Board link |

---

## Scheduled jobs

| Schedule | Job |
|----------|-----|
| Daily | `container_tracker.refresh_open_container_metrics` |

Ensure scheduler is running: `bench doctor` / supervisor.

---

## Upgrades

```bash
cd apps/cgm_shipping && git pull
bench --site <site> migrate
bench build --app cgm_shipping   # if JS/CSS changed
bench restart
bench --site <site> clear-cache
```

---

## Troubleshooting

| Issue | Check |
|-------|-------|
| PDF print fails | Chrome installed? Print format `pdf_generator = chrome` |
| Tasks not created on Project | Shipment Type sea-import flag; Opportunity → Project path |
| Cannot advance shipment status | Task gates + document verification in Settings |
| Finance cost total wrong | JE `custom_cgm_source_task` link; do not edit total manually |
| Portal redirect loop | Website user roles; `website.py` hooks |

---

## Documentation

| Resource | Path |
|----------|------|
| Docs hub | `apps/cgm_shipping/docs/README.md` |
| Full reference | `apps/cgm_shipping/docs/full-documentation.md` |
| Frappe Wiki sidebar | `apps/cgm_shipping/docs/.wiki.json` |
| Frappe Wiki (Desk) | `/cgm-shipping/` after `install-app wiki` + migrate |

---

## Related guides

- [Developer](developer.md)
- [Operations](operations.md)
- [Finance](finance.md)
