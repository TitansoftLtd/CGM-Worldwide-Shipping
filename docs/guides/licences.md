# Licence & Permit Register

For **Admin**, **Compliance**, and anyone responsible for keeping a company licence current. Covers recording licences, the expiry reminder schedule, and who gets notified.

This register tracks the **company's own** licences and permits — trading licences, NTSA/KRA registrations, agency bonds, insurance certificates. It is unrelated to the per-shipment **Permit Register** on Opportunity/Project, which tracks permits applied for on behalf of a client.

---

## Where to work

| Item | Path in Desk |
|------|--------------|
| Licences | **License Register** |
| Issuing bodies and agents | **Licensing Contact** |
| Categories of licence | **License Type** |
| What was sent, and when | **License Reminder Log** |
| Schedule and recipients | **License Settings** |

All five are on the **CGM Shipping** workspace under **Licences & Permits**, and in the sidebar.

---

## Recording a licence

| Field | Notes |
|-------|-------|
| **Licence / Permit** | As it appears on the certificate |
| **Type** | Link to **License Type**. If the type has a default validity, the expiry date is suggested from the issue date |
| **Company** | Required — reminders quote it |
| **Renewal Basis** | Decides how the licence is chased. See below |
| **Service Provider** | Link to **Licensing Contact**; contact person, phone and email are pulled in |
| **Responsible Person** | Notified in addition to the standing recipients, if enabled in settings |
| **Additional Recipients** | Extra addresses for this licence only, comma separated |

### Renewal basis

| Basis | Behaviour |
|-------|-----------|
| **Fixed Expiry Date** | Expiry date is mandatory. Reminders are counted back from it |
| **Ongoing / No Expiry** | Tracked, never chased |
| **Renew When Needed** | No date to work from — gets a periodic review nudge instead |

**Status** and **Days to Expiry** are set by the system and refreshed every night; you cannot edit them.

| Status | Meaning |
|--------|---------|
| Active | Beyond the widest reminder period |
| Expiring Soon | Inside the widest reminder period |
| Expired | Past the expiry date |
| Renewal Required | Renew When Needed, or Fixed Expiry with no date set |
| Ongoing | Ongoing / No Expiry |
| Disabled | **Disabled** ticked — no status tracking, no reminders |

---

## The reminder schedule

Reminder periods are days counted back from the expiry date. With the default schedule of **90 / 60 / 30 / 14 / 7**, a licence expiring on 30 June is chased on 1 April, 1 May, 31 May, 16 June and 23 June.

Two rules matter:

- **The tightest band that has been crossed wins.** A licence entered when it is already 45 days from expiry gets one reminder (the 60-day one), not one for every band it skipped.
- **Each band fires once per expiry date.** Renewing a licence sets a new expiry date, which is a new schedule, so the bands fire again. Correcting a mistyped date back to what it was does *not* re-send.

Use **Reminder Schedule** on the licence form to see the dates, what has already gone out, and who is on the list — without waiting for the nightly job.

### Per-licence overrides

Tick **Override Reminder Periods** on a licence to give it its own schedule instead of the default. Only shown for Fixed Expiry Date licences.

---

## Settings

**License Settings** (single doctype, System Manager or License Manager):

| Section | Controls |
|---------|----------|
| **Expiry Notifications** | Master switch, plus email and/or in-app delivery |
| **Notification Periods** | The default schedule for every licence that does not override it |
| **Recipients** | Notify Users, Notify Roles, the licence's own Responsible Person, and plain email addresses with no user account |
| **Already Expired** | Whether to keep chasing after expiry, how often, and when to give up |
| **Renew When Needed** | How often to nudge licences that have no fixed expiry date |

Two buttons on the form:

- **Preview Today's Reminders** — dry run. Shows what would go out and to whom. Sends nothing, logs nothing.
- **Send Reminders Now** — runs the nightly check immediately, for real.

The widest notification period doubles as the **Expiring Soon** window, so the status flips to a warning on the same day the first reminder goes out. Saving the settings re-runs the status calculation in the background.

---

## Reminder Log

Every send is written to **License Reminder Log** — licence, reminder type, days, expiry date, channels, recipients, and any error. This is also what stops the same reminder going out twice, so do not delete rows to "test" a reminder; use **Preview Today's Reminders** instead.

A send that fails on every channel is logged as **Failed** and stays due, so the next nightly run tries again.

---

## Roles

| Role | Can do |
|------|--------|
| **License Manager** | Full access to licences, types, contacts, settings and the log |
| **License User** | Read licences, types and contacts |

Both are created on install and on every migrate.

---

## Troubleshooting

| Issue | Check |
|-------|-------|
| No reminders arriving | **Enable Expiry Notifications** on; at least one of Email / In-App on; at least one notification period set |
| Reminders due but nobody receives them | Recipients in License Settings — **Preview Today's Reminders** shows an empty list when nobody is configured |
| Email fails, in-app works | Outgoing Email Account on the site. In-app is attempted first precisely so a site with no mail set up still gets its reminders |
| Status stuck on Active near expiry | The widest notification period *is* the warning window. Add a wider period, or save License Settings to re-run the calculation |
| A licence renewed but still chased | Confirm the expiry date actually moved — bands are keyed on the expiry date |

---

## Related guides

- [Admin & Setup](admin-setup.md)
- [Declaration & Customs](declaration-customs.md) — per-shipment permits, which are a different thing
