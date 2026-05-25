# CGM Shipping — Requirements Roadmap

Items marked ✅ have baseline support in the app today. Others are planned phases.

## Container & operations (✅ in progress)

| Requirement | Status |
|-------------|--------|
| Project = shipment master | ✅ |
| Before berth / after berth tracking | ✅ [CONTAINER_TRACKING_FLOW.md](CONTAINER_TRACKING_FLOW.md) |
| Container Tracker (Mombasa / ICD / Transit) | ✅ |
| Demurrage / detention / free days auto-calc | ✅ |
| Seal records (Mombasa / Nairobi / Malaba) | ✅ |
| Daily Status Update + RAG + email | ✅ |
| Empty return tracking + overdue status | ✅ |

## Quotes & commercial (planned)

| Requirement | Status |
|-------------|--------|
| Separate Air / LCL / FCL product types | ✅ Shipment Type on CRM/Project |
| Auto-referencing of quotes | 🔲 Link Quotation → Project |
| Auto tax calculation (editable duty %) | 🔲 Quotation / SI line logic |
| Inclusive rate calculation | 🔲 Quotation template |
| Created by / edited / approved by | 🔲 Standard ERPNext + workflow |
| Approval workflow + “approved by” | 🔲 Quotation workflow |
| Edit in place (keep reference) | 🔲 ERPNext amend pattern |
| Tracking: Sent / Approved / Pending | 🔲 Quotation status |
| Incoterm: FOB / Ex-works / Door to door | 🔲 Custom field on Quotation |
| Rate subject to change clause | 🔲 Terms template |
| User access control on editing | 🔲 Role permissions |
| Reports | 🔲 Script Report pack |
| New customer from quote | ✅ Lead/Customer flow |
| Standard rates library | 🔲 Rate Card doctype |

## Notifications (planned)

| Requirement | Status |
|-------------|--------|
| Email on Red/Yellow daily status | ✅ partial |
| WhatsApp to supervisors | 🔲 Integration (e.g. Twilio / Meta API) |
