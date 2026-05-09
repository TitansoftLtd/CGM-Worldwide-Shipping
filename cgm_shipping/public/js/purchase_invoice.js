frappe.ui.form.on("Purchase Invoice", {
	on_submit(frm) {
		link_purchase_invoice_back_to_task(frm);
	},
});

function link_purchase_invoice_back_to_task(frm) {
	const task_name = localStorage.getItem("cgm_return_task");
	const pi_flow = localStorage.getItem("cgm_pi_for_task");
	if (!task_name || !frm.doc.name || frm.doc.docstatus !== 1 || pi_flow !== "1") {
		return;
	}

	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.utils.link_purchase_invoice_to_task",
		args: {
			task_name,
			purchase_invoice: frm.doc.name,
		},
		callback(r) {
			if (r.exc) {
				return;
			}
			localStorage.removeItem("cgm_pi_for_task");
			localStorage.removeItem("cgm_return_task");
			frappe.show_alert({
				message: __("Purchase Invoice linked. Use **Make Payment** on the task next."),
				indicator: "green",
			});
			frappe.set_route("Form", "Task", task_name);
		},
	});
}
