frappe.ui.form.on("Purchase Invoice", {
	onload(frm) {
		persist_cgm_source_task(frm);
		apply_task_finance_defaults(frm);
	},

	refresh(frm) {
		add_cgm_finance_buttons(frm);
	},

	on_submit(frm) {
		const task_name = get_cgm_source_task(frm);
		if (task_name) {
			localStorage.setItem("cgm_return_task", task_name);
			localStorage.setItem("cgm_pe_for_task", "1");
		}
		frappe.after_ajax(() => {
			if (flt(frm.doc.outstanding_amount) > 0 && !frm.doc.on_hold) {
				open_payment_from_purchase_invoice(frm);
			} else {
				return_to_cgm_task(frm, {
					message: __(
						"Purchase Invoice submitted — returning to task {0}. Receipt verification may continue there.",
						[task_name]
					),
				});
			}
		});
	},
});

frappe.ui.form.on("Purchase Invoice Item", {
	item_code(frm, cdt, cdn) {
		restore_cgm_permit_rate_for_row(frm, cdt, cdn);
	},
});

function get_cgm_source_task(frm) {
	return (
		localStorage.getItem("cgm_return_task") ||
		frm.doc.custom_cgm_source_task ||
		null
	);
}

function persist_cgm_source_task(frm) {
	const task_name = localStorage.getItem("cgm_return_task");
	if (!task_name || !frm.fields_dict.custom_cgm_source_task) {
		return;
	}
	if (!frm.doc.custom_cgm_source_task) {
		frm.set_value("custom_cgm_source_task", task_name);
	}
}

function add_cgm_finance_buttons(frm) {
	const task_name = get_cgm_source_task(frm);
	if (!task_name) {
		return;
	}

	frm.add_custom_button(__("Back to Task"), () => {
		frappe.set_route("Form", "Task", task_name);
	}, __("CGM"));

	if (frm.doc.docstatus === 1 && flt(frm.doc.outstanding_amount) > 0 && !frm.doc.on_hold) {
		frm.add_custom_button(
			__("Make Payment"),
			() => open_payment_from_purchase_invoice(frm),
			__("CGM")
		);
		frm.page.set_inner_btn_group_as_primary(__("CGM"));
	}
}

function open_payment_from_purchase_invoice(frm) {
	const task_name = get_cgm_source_task(frm);
	if (!frm.doc.name || frm.doc.docstatus !== 1) {
		frappe.msgprint(__("Submit the Purchase Invoice before making payment."));
		return;
	}
	if (flt(frm.doc.outstanding_amount) <= 0) {
		return_to_cgm_task(frm);
		return;
	}

	frappe.call({
		method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
		args: {
			dt: "Purchase Invoice",
			dn: frm.doc.name,
		},
		freeze: true,
		freeze_message: __("Building Payment Entry…"),
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			const doclist = frappe.model.sync(r.message);
			const pe = doclist[0];
			if (pe && task_name) {
				if (frm.fields_dict.custom_cgm_source_task || pe.custom_cgm_source_task !== undefined) {
					frappe.model.set_value(pe.doctype, pe.name, "custom_cgm_source_task", task_name);
				}
				if (frm.doc.project) {
					frappe.model.set_value(pe.doctype, pe.name, "project", frm.doc.project);
				}
				localStorage.setItem("cgm_return_task", task_name);
				localStorage.setItem("cgm_pe_for_task", "1");
			}
			frappe.show_alert({
				message: __("Submit payment — you will return to the finance task."),
				indicator: "blue",
			});
			frappe.set_route("Form", "Payment Entry", pe.name);
		},
	});
}

function return_to_cgm_task(frm, opts = {}) {
	const task_name = get_cgm_source_task(frm);
	if (!task_name || frm.__cgm_returned_to_task) {
		return;
	}
	frm.__cgm_returned_to_task = true;
	localStorage.removeItem("cgm_pi_for_task");
	localStorage.removeItem("cgm_return_task");
	frappe.show_alert({
		message: opts.message || __("Returning to task {0}", [task_name]),
		indicator: "green",
	});
	frappe.set_route("Form", "Task", task_name);
}

function apply_task_finance_defaults(frm) {
	if (!frm.is_new() || frm._cgm_permit_defaults_applied) {
		return;
	}
	const task_name = get_cgm_source_task(frm);
	if (!task_name) {
		return;
	}
	frm._cgm_permit_defaults_applied = true;
	localStorage.setItem("cgm_return_task", task_name);
	localStorage.setItem("cgm_pi_for_task", "1");

	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.get_task_finance_defaults",
		args: { task_name },
		callback(r) {
			if (r.exc || !r.message) {
				frm._cgm_permit_defaults_applied = false;
				return;
			}
			const defaults = r.message.purchase_invoice_defaults || {};
			const permit_items = r.message.permit_line_items || [];

			set_purchase_invoice_header_defaults(frm, defaults).then(() => {
				if (!permit_items.length) {
					frappe.show_alert({
						message: __(
							"Submit this invoice, then use CGM → Make Payment. You will return to task {0}.",
							[task_name]
						),
						indicator: "blue",
					});
					return;
				}
				apply_permit_lines_to_purchase_invoice(frm, permit_items).then(() => {
					frappe.show_alert({
						message: __(
							"Added {0} permit line(s) from task {1} — submit, then use CGM → Make Payment.",
							[permit_items.length, task_name]
						),
						indicator: "green",
					});
				});
			});
		},
	});
}

function set_purchase_invoice_header_defaults(frm, defaults) {
	const entries = Object.entries(defaults).filter(
		([field, value]) => value != null && value !== "" && frm.fields_dict[field]
	);
	return entries.reduce(
		(chain, [field, value]) => chain.then(() => frm.set_value(field, value)),
		Promise.resolve()
	);
}

function restore_cgm_permit_rate_for_row(frm, cdt, cdn) {
	if (!frm.cgm_applying_permit_lines || !frm.cgm_permit_line_rates?.[cdn]) {
		return;
	}
	const snap = frm.cgm_permit_line_rates[cdn];
	// ERPNext item_code / process_item_selection overwrites rate asynchronously.
	frappe.after_ajax(() => {
		frappe.after_ajax(() => {
			set_permit_line_amounts(cdt, cdn, snap);
		});
	});
}

function set_permit_line_amounts(cdt, cdn, row) {
	const qty = flt(row.qty) || 1;
	const rate = flt(row.rate);
	return frappe.model.set_value(cdt, cdn, {
		qty,
		rate,
		amount: rate * qty,
		description: row.description || "",
		project: row.project || "",
	});
}

function apply_permit_lines_to_purchase_invoice(frm, permit_items) {
	const rows = (permit_items || []).filter((row) => flt(row.rate) > 0 && row.item_code);
	frm.clear_table("items");

	if (!rows.length) {
		frm.refresh_field("items");
		return Promise.resolve();
	}

	frm.cgm_applying_permit_lines = true;
	frm.cgm_permit_line_rates = {};
	frm.disable_save();

	let chain = Promise.resolve();
	rows.forEach((row) => {
		chain = chain.then(() => add_one_permit_line(frm, row));
	});

	return chain.then(() => {
		frm.cgm_applying_permit_lines = false;
		frm.cgm_permit_line_rates = null;
		frm.enable_save();
		if (typeof frm.trigger === "function") {
			frm.trigger("calculate_taxes_and_totals");
		}
		frm.refresh_field("items");
	});
}

function add_one_permit_line(frm, row) {
	return new Promise((resolve) => {
		const child = frm.add_child("items");
		frm.cgm_permit_line_rates[child.name] = row;
		const cdt = child.doctype;
		const cdn = child.name;

		frappe.model
			.set_value(cdt, cdn, {
				item_code: row.item_code,
				qty: row.qty || 1,
				rate: row.rate,
				amount: flt(row.rate) * flt(row.qty || 1),
				description: row.description || "",
				project: row.project || frm.doc.project,
			})
			.then(() => {
				frappe.after_ajax(() => {
					frappe.after_ajax(() => {
						set_permit_line_amounts(cdt, cdn, row).then(resolve);
					});
				});
			});
	});
}
