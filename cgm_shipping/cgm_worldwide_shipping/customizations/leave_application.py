"""Leave Application guards."""

import frappe
from frappe import _

REQUIRES_ATTACHMENT_FIELD = "custom_requires_attachment"
SUPPORTING_DOCUMENT_FIELD = "custom_supporting_document"


def validate_required_attachment(doc, method=None):
	"""Block leave types flagged "Attachment Required" that carry no document.
	"""
	if not doc.leave_type or doc.get(SUPPORTING_DOCUMENT_FIELD):
		return

	if not frappe.db.get_value("Leave Type", doc.leave_type, REQUIRES_ATTACHMENT_FIELD):
		return

	frappe.throw(
		_("{0} requires a supporting document. Attach one in {1} before saving.").format(
			frappe.bold(doc.leave_type), frappe.bold(_("Supporting Document"))
		),
		title=_("Attachment Required"),
	)
