"""Sea clearance tasks need many attachments (permit rows, invoices, receipts)."""
import frappe

from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	# ERPNext Task default is 5; permit tasks need one invoice per agency + finance docs.
	limit = 40
	make_property_setter("Task", None, "max_attachments", limit, "int", for_doctype=True)
	frappe.clear_cache(doctype="Task")
