frappe.ui.form.on("Purchase Invoice", {
	onload(frm) {
		apply_task_finance_defaults(frm);
	},

	on_submit(frm) {
		link_purchase_invoice_back_to_task(frm);
	},
});

function apply_task_finance_defaults(frm) {
	if (!frm.is_new()) {
		return;
	}
	const task_name = localStorage.getItem("cgm_return_task");
	if (!task_name || localStorage.getItem("cgm_pi_for_task") !== "1") {
		return;
	}

	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.get_task_finance_defaults",
		args: { task_name },
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			const defaults = r.message.purchase_invoice_defaults || {};
			Object.entries(defaults).forEach(([field, value]) => {
				if (value != null && value !== "" && frm.fields_dict[field]) {
					frm.set_value(field, value);
				}
			});

			const permit_items = r.message.permit_line_items || [];
			if (permit_items.length) {
				apply_permit_lines_to_purchase_invoice(frm, permit_items);
				frappe.show_alert({
					message: __(
						"Added {0} permit line(s) from task {1} — review amounts and supplier, then save.",
						[permit_items.length, task_name]
					),
					indicator: "green",
				});
			} else {
				frappe.show_alert({
					message: __("Project {0} set from task {1}", [defaults.project, task_name]),
					indicator: "blue",
				});
			}
		},
	});
}

function apply_permit_lines_to_purchase_invoice(frm, permit_items) {
	frm.clear_table("items");
	permit_items.forEach((row) => {
		const child = frm.add_child("items");
		frappe.model.set_value(child.doctype, child.name, {
			item_code: row.item_code,
			item_name: row.item_name,
			description: row.description,
			qty: row.qty || 1,
			rate: row.rate,
			amount: row.amount,
			project: row.project || frm.doc.project,
		});
	});
	frm.refresh_field("items");
}

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
				message: __(
					"Purchase Invoice linked to {0}. Project: {1}. Use **Make Payment** on the task.",
					[task_name, r.message.project || frm.doc.project]
				),
				indicator: "green",
			});
			frappe.set_route("Form", "Task", task_name);
		},
	});
}
