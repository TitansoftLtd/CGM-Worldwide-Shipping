# CGM Shipping — Project structure (single app & module)

All shipment-guide functionality lives in the existing `**cgm_shipping**` app and `**CGM Worldwide Shipping**` module — no separate app or module.

## Layout

```
apps/cgm_shipping/
└── cgm_shipping/
    └── cgm_worldwide_shipping/
        ├── doctype/           # All custom doctypes (CRM + shipment guide)
        ├── custom/            # Project, Lead, Quotation, Payment Entry, …
        ├── customizations/    # Project, Task, Customer hooks
        ├── overrides/         # Payment Entry → Shipment Dossier
        ├── test_data/         # E2E seed script
        ├── workspace/         # CGM Worldwide Shipping desk workspace
        └── fixtures/          # (via app-level fixtures/)
```

## Shipment guide doctypes (master: Shipment Dossier)


| Doctype                  | Purpose                          |
| ------------------------ | -------------------------------- |
| Shipment Dossier         | Master clearance file            |
| Permit Register          | Child table on dossier           |
| CFS Master               | CFS / depot master               |
| IDF UCR Record           | Declaration                      |
| Customs Entry            | Entry & taxes                    |
| Container Tracker        | Container lifecycle + demurrage  |
| Daily Status Update      | Team daily log (Red RAG → email) |
| Shipping Line Charges    | Line charges / DO                |
| Port Charges KPA Invoice | KPA / gate pass                  |
| Seal Record              | Seal tracking                    |
| Export Shipment          | Export corridor                  |
| Interchange Receipt      | Empty return                     |


## Legacy records (same module)

Still available for migration / reference:

- **Project** custom fields + **CGM Sea Import Workflow**
- **Shipment tracker** (older tracker; prefer **Shipment Dossier** + **Container Tracker**)
- **Shipment Document**, **Document Type**, **CGM Shipping Settings**
- CRM Lead / Opportunity pre-shipment workflows

Optional link: **Shipment Dossier** → **Linked Project**.

## Workflow

**Shipment Clearance Workflow** on **Shipment Dossier**  
Status: Draft → Documents Received → … → Settled

## Setup

```bash
bench --site <site> migrate
bench --site <site> execute cgm_shipping.cgm_worldwide_shipping.test_data.seed_e2e_test_data.seed
```

See [TEST_E2E.md](TEST_E2E.md) for manual UAT.

## Not yet built

- Role dashboards (Operations, Transport, Finance)
- Six script/query reports
- Full notification set (IDF → Finance, demurrage alerts)
- Bulk migration Project / Shipment tracker → Shipment Dossier

