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
