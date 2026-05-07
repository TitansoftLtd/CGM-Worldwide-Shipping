frappe.ui.form.on("Shipment Document", {
	attachment: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.attachment) {
			if (!row.status || row.status === "Missing") {
				frappe.model.set_value(cdt, cdn, "status", "Uploaded");
			}
			if (!row.uploaded_by) {
				frappe.model.set_value(cdt, cdn, "uploaded_by", frappe.session.user);
			}
		} else {
			frappe.model.set_value(cdt, cdn, "status", "Missing");
			frappe.model.set_value(cdt, cdn, "uploaded_by", "");
			frappe.model.set_value(cdt, cdn, "uploaded_on", "");
			frappe.model.set_value(cdt, cdn, "verified_by", "");
			frappe.model.set_value(cdt, cdn, "verified_on", "");
		}
	},

	status: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (["Verified", "Rejected"].includes(row.status)) {
			if (!row.attachment) {
				frappe.msgprint(__("Attach a file before verification."));
				frappe.model.set_value(cdt, cdn, "status", "Missing");
				return;
			}
			frappe.model.set_value(cdt, cdn, "verified_by", frappe.session.user);
			frappe.model.set_value(cdt, cdn, "verified_on", frappe.datetime.now_datetime());
		} else if (row.status === "Uploaded") {
			frappe.model.set_value(cdt, cdn, "verified_by", "");
			frappe.model.set_value(cdt, cdn, "verified_on", "");
		}
	},
});

frappe.ui.form.on("Project", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0 || frm.doc.custom_mode_of_transport !== "Sea") {
			return;
		}
		frm.add_custom_button(__("Generate Sea Task Plan"), () => {
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.customizations.utils.create_sea_import_task_plan",
				args: { project: frm.doc.name },
				freeze: true,
				callback(r) {
					if (!r.exc) {
						frappe.show_alert({
							message: __("Sea task plan generated"),
							indicator: "green",
						});
					}
				},
			});
		});
	},
});
