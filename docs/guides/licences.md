---
title: Licence & Permit Register
metatags:
  description: Company licence register — record certificates, expiry reminder schedule, recipients, License Settings, and troubleshooting. Not client shipment permits.
---

# Licence & Permit Register

**Keep the company’s own licences and permits current — trading licences, NTSA/KRA registrations, bonds, insurance.**

Use this guide for Admin and Compliance. This register is **not** the per-shipment **Permit Register** on Opportunity/Project (client clearance permits).

A typical scenario: You record a bond with Fixed Expiry Date, set the service provider, and rely on the nightly 90/60/30/14/7 schedule to email License Managers before expiry.

To access licences, go to:

> Home > CGM Shipping > License Register

Also use:

> Home > CGM Shipping > License Settings

## 1. Prerequisites

- Role **License Manager** (full) or **License User** (read)
- **License Type** and **Licensing Contact** masters as needed
- Outgoing Email Account if email reminders are required (in-app still works without mail)

## 2. How to — record a licence

| Field | Notes |
|-------|-------|
| **Licence / Permit** | As on the certificate |
| **Type** | Link to **License Type** (may suggest expiry from issue date) |
| **Company** | Required — quoted in reminders |
| **Renewal Basis** | Fixed Expiry / Ongoing / Renew When Needed |
| **Service Provider** | **Licensing Contact** |
| **Responsible Person** / **Additional Recipients** | Extra notify targets |

| Renewal basis | Behaviour |
|---------------|-----------|
| **Fixed Expiry Date** | Expiry mandatory; reminders count back from it |
| **Ongoing / No Expiry** | Tracked, never chased |
| **Renew When Needed** | Periodic review nudge |

**Status** and **Days to Expiry** are system-calculated nightly.

| Status | Meaning |
|--------|---------|
| Active | Beyond widest reminder period |
| Expiring Soon | Inside widest reminder period |
| Expired | Past expiry |
| Renewal Required | Renew When Needed, or Fixed with no date |
| Ongoing | Ongoing / No Expiry |
| Disabled | Disabled ticked — no reminders |

## 3. Features — Reminder schedule

Default periods **90 / 60 / 30 / 14 / 7** days before expiry. Tightest band that has been crossed wins; each band fires once per expiry date. Use **Reminder Schedule** on the form to preview without waiting for the job.

**Override Reminder Periods** on a Fixed Expiry licence for a custom schedule.

## 4. How to — License Settings

| Section | Controls |
|---------|----------|
| **Expiry Notifications** | Master switch; email and/or in-app |
| **Notification Periods** | Default schedule |
| **Recipients** | Users, roles, Responsible Person, plain emails |
| **Already Expired** | Chase after expiry |
| **Renew When Needed** | Nudge frequency |

**Preview Today's Reminders** (dry run) and **Send Reminders Now** (live). Every send is logged in **License Reminder Log** — do not delete log rows to retest; use Preview.

## 5. Features — Roles

| Role | Can do |
|------|--------|
| **License Manager** | Full access including settings and log |
| **License User** | Read licences, types, contacts |

## 6. How to — Troubleshooting

| Issue | Check |
|-------|-------|
| No reminders | Enable notifications; periods set; recipients configured |
| Empty Preview list | Add recipients in License Settings |
| Email fails, in-app works | Outgoing Email Account |
| Status stuck Active near expiry | Widen periods or save Settings to recalculate |
| Renewed but still chased | Confirm expiry date actually changed |

## 7. Related Topics

- [Declaration & Customs](declaration-customs.md) — client shipment permits
- [Payroll & HR](payroll-hr.md)
