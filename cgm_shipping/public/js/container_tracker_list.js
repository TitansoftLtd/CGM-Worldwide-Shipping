// Colour in the Container Tracker list.
//
// `status` is a Data field holding a derived lifecycle stage, and Frappe only
// colours a list row on its own for Select and workflow fields. So the form showed a
// coloured indicator and the list showed none, which is the wrong way round: the list
// is where you skim a shipment's boxes looking for the one with a problem.
//
// The colour comes from `frappe.boot.cgm_container_statuses`, served from
// CONTAINER_STATUS_TABLE in customizations/constants.py, so the list, the form, the
// report and the Ops Board all read the same rows. A status missing from that table
// falls back to grey rather than guessing.
frappe.listview_settings["Container Tracker"] = {
	add_fields: ["status"],

	get_indicator(doc) {
		if (!doc.status) {
			return [__("No Status"), "gray", "status,is,not set"];
		}

		const colour = cgm_shipping.container_tracking.status_color(doc.status);
		// Clicking the pill filters the list to that status, which is the usual next
		// move after spotting one.
		return [__(doc.status), colour, "status,=," + doc.status];
	},
};
