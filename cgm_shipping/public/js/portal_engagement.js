// Copyright (c) 2026, Titansoft Limited and contributors
/**
 * Desk hook for portal engagement on Container Tracker: post an update to the
 * customer / transporter portal.
 *
 * The dialog itself lives in operational_updates_ui.js so the ops board and the
 * form open exactly the same publish flow. The Project form has none of this -
 * it posts from the Post update button on its Shipment Updates tab, beside the
 * conversations the update joins. Portal feedback is read on the Portal
 * Feedback list, not from a button here.
 */
frappe.provide("cgm.portal_engagement");

(() => {
	cgm.portal_engagement.addContainerButtons = function (frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(
			__("Post Update"),
			() => {
				cgm.updates.openPublishDialog({
					project: frm.doc.project,
					container_tracker: frm.doc.name,
				});
			},
			__("Portal")
		);
	};

	frappe.ui.form.on("Container Tracker", {
		refresh(frm) {
			cgm.portal_engagement.addContainerButtons(frm);
		},
	});
})();
