# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CGMTaskTemplate(Document):
	pass


def sync_open_tasks_from_template(doc, _method=None):
	"""When admins edit Required Document Types, push changes onto open Tasks."""
	if frappe.flags.in_import or frappe.flags.in_patch:
		return
	from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_seed_data import (
		sync_tasks_for_template,
	)

	sync_tasks_for_template(doc.name)
