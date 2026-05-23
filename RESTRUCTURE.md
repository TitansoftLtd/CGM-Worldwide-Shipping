# CGM Shipping — Project + Task architecture

## Single clearance master: **Project**

All guide functionality (documents, permits, UCR, entry, containers, workflow) is on **Project** and **Task**.

| Component | Location |
|-----------|----------|
| Workflow | **CGM Sea Import Workflow** on **Project** → `custom_shipment_status` |
| Client documents | `custom_shipment_documents` |
| Permits | `custom_permit_register` |
| Linked records | IDF UCR Record, Customs Entry, Container Tracker, … → **project** |
| Sea steps | **Task** plan (Generate Sea Task Plan) |
| Payments | Standard **project** on Payment Entry / Purchase Invoice |

**Shipment Dossier** is inactive; use **Project** only for new work.

See [OPERATIONS_PROCESS.md](OPERATIONS_PROCESS.md) for the full Lead → Project → DONE process.  
See [SEA_FREIGHT_PROCESS.md](SEA_FREIGHT_PROCESS.md) for the sea workflow state chart.
