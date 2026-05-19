"""Task hooks — sync Task Documents to the parent Project shipment file."""


def on_task_update(doc, _method=None):
	if not doc.get("project"):
		return

	from cgm_shipping.cgm_worldwide_shipping.customizations.utils import refresh_project_shipment_documents

	refresh_project_shipment_documents(doc.project)
