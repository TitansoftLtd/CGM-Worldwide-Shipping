frappe.ui.form.on("Payment Entry", {
	after_save(frm) {
		link_payment_back_to_task(frm);
	},
	on_submit(frm) {
		link_payment_back_to_task(frm);
	},
});

function link_payment_back_to_task(frm) {
	const task_name = localStorage.getItem("cgm_return_task");
	if (!task_name || !frm.doc.name || frm.doc.docstatus !== 1) {
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
			frappe.show_alert({
				message: __("Payment linked and task completed"),
				indicator: "green",
			});
			frappe.set_route("Form", "Task", task_name);
		},
	});
}
