frappe.ui.form.on("Lead", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		// Client scripts run before ERPNext LeadController.refresh(), which adds
		// Create / Action groups. Defer cleanup until after that handler runs.
		setTimeout(() => {
			cleanup_lead_toolbar(frm);

			if (frm.doc.custom_cgm_preshipment_status !== "Lead Ready to Convert") {
				return;
			}

			if (frm.doc.customer || frm.doc.__onload?.is_customer) {
				return;
			}

			frm.add_custom_button(__("Customer"), () => {
				frappe.model.open_mapped_doc({
					method: "erpnext.crm.doctype.lead.lead.make_customer",
					frm,
				});
			}).addClass("btn-primary");
		}, 0);
	},
});

function cleanup_lead_toolbar(frm) {
	// ERPNext adds mapped-doc shortcuts under these inner groups (not removable by label alone).
	for (const group of [__("Create"), __("Action")]) {
		frm.page.get_inner_group_button(group)?.remove();
	}

	if (!frm.page.inner_toolbar.children().length) {
		frm.page.inner_toolbar.addClass("hide");
	}

	// Hide the "..." menu; keep the primary Actions dropdown used by workflow.
	frm.page.hide_menu();
}
