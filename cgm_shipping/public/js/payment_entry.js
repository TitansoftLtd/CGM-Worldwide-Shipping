frappe.ui.form.on("Payment Entry", {
	onload(frm) {
		if (frm.is_new() && localStorage.getItem("cgm_pe_for_task") === "1") {
			const task_name = localStorage.getItem("cgm_return_task");
			if (task_name && !frm.doc.custom_cgm_source_task && frm.fields_dict.custom_cgm_source_task) {
				frm.set_value("custom_cgm_source_task", task_name);
			}
		}
	},

	after_save(frm) {
		link_payment_back_to_task(frm);
	},
	on_submit(frm) {
		link_payment_back_to_task(frm);
	},
});

function link_payment_back_to_task(frm) {
	const task_name = localStorage.getItem("cgm_return_task");
	const pe_flow = localStorage.getItem("cgm_pe_for_task");
	if (!task_name || !frm.doc.name || frm.doc.docstatus !== 1 || pe_flow !== "1") {
		return;
	}

	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.utils.complete_task_with_payment",
		args: {
			task_name,
			payment_entry: frm.doc.name,
		},
		callback(r) {
			if (r.exc) {
				return;
			}
			localStorage.removeItem("cgm_return_task");
			localStorage.removeItem("cgm_pe_for_task");
			const msg =
				r.message?.message ||
				(r.message?.auto_completed === false
					? __("Payment recorded — upload and verify receipts before completing the task")
					: __("Payment linked and task completed"));
			frappe.show_alert({ message: msg, indicator: "green" });
			frappe.set_route("Form", "Task", task_name);
		},
	});
}
