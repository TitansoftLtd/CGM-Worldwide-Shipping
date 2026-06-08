"""Task document class - strip legacy invoice rows before Frappe link validation."""
from __future__ import annotations

from erpnext.projects.doctype.task.task import Task


class CGMTask(Task):
	def _save(self, ignore_permissions=None, ignore_version=None):
		self._strip_legacy_invoice_clearance_documents()
		return super()._save(
			ignore_permissions=ignore_permissions,
			ignore_version=ignore_version,
		)

	def insert(
		self,
		ignore_permissions=None,
		ignore_links=None,
		ignore_if_duplicate=False,
		ignore_mandatory=None,
		set_name=None,
		set_child_names=True,
	):
		self._strip_legacy_invoice_clearance_documents()
		return super().insert(
			ignore_permissions=ignore_permissions,
			ignore_links=ignore_links,
			ignore_if_duplicate=ignore_if_duplicate,
			ignore_mandatory=ignore_mandatory,
			set_name=set_name,
			set_child_names=set_child_names,
		)

	def _strip_legacy_invoice_clearance_documents(self) -> None:
		from cgm_shipping.cgm_worldwide_shipping.customizations.task_finance import (
			migrate_invoice_attachments_from_documents,
			purge_invoice_rows_from_task_documents_db,
			remove_invoice_rows_from_task_documents,
		)

		if self.name and not self.get("__islocal"):
			purge_invoice_rows_from_task_documents_db(self.name)
		migrate_invoice_attachments_from_documents(self)
		remove_invoice_rows_from_task_documents(self)
