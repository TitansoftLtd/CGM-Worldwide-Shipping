"""Task vs Project documents (CGM policy).

Working papers (permit applications, fee assessments, authority invoices, screenshots,
payment slips during a step) belong on the Task: use **Attachments** on the Task and/or
optional **Task Documents** rows on the Task form — they are **not** auto-copied to Project.

Permanent shipment evidence (CI, PKL, BL/AWB, KRA PIN, **final** approved permits, etc.)
belongs in **Project → Shipment Documents**. Add those there deliberately when they are
the official file for the shipment.

Previous behaviour that synced Task document rows into Project on every save was removed
to avoid cluttering the shipment file with temporary operational documents.
"""
