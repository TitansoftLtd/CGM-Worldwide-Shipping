frappe.ui.form.on("Leave Application", {
	before_workflow_action(frm) {
		if (frm.selected_workflow_action === "Reject") {
			return prompt_leave_rejection_reason(frm);
		}
	},
});

function prompt_leave_rejection_reason(frm) {
	frappe.dom.unfreeze();
	return new Promise((resolve) => {
		const dialog = new frappe.ui.Dialog({
			title: __("Reject Leave Application"),
			fields: [
				{
					fieldname: "custom_reason_for_rejection",
					fieldtype: "Small Text",
					label: __("Reason for Rejection"),
					reqd: 1,
				},
			],
			primary_action_label: __("Reject"),
			primary_action(values) {
				dialog.hide();
				frm.set_value("custom_reason_for_rejection", values.custom_reason_for_rejection)
					.then(() => frm.save())
					.then(() => resolve());
			},
			secondary_action_label: __("Cancel"),
			secondary_action() {
				dialog.hide();
			},
		});
		dialog.show();
	});
}
