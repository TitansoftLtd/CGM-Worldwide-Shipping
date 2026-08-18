frappe.ui.form.on("Purchase Invoice", {
	onload(frm) {
		persist_cgm_source_task(frm);
		apply_task_defaults(frm);
	},

	refresh(frm) {
		add_cgm_finance_buttons(frm);
		refresh_transporter_share_ui(frm);
	},

	supplier(frm) {
		refresh_transporter_share_ui(frm);
	},

	custom_share_with_transporter(frm) {
		toggle_transporter_share_fields(frm);
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
	frm.page.set_inner_btn_group_as_primary(__("CGM"));
}

function apply_task_defaults(frm) {
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
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.task.get_task_defaults",
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
					return;
				}
				apply_permit_lines_to_purchase_invoice(frm, permit_items).then(() => {
					frappe.show_alert({
						message: __("Added {0} line(s) from task {1}.", [permit_items.length, task_name]),
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

function supplier_is_transporter_on_invoice(frm) {
	if (frm._cgm_supplier_is_transporter != null) {
		return cint(frm._cgm_supplier_is_transporter);
	}
	return cint(frm.doc.custom_supplier_is_transporter);
}

function refresh_transporter_share_ui(frm) {
	if (!frm.fields_dict.custom_share_with_transporter) {
		return;
	}
	if (!frm.doc.supplier) {
		frm._cgm_supplier_is_transporter = 0;
		if (
			frm.doc.docstatus === 0 &&
			frm.fields_dict.custom_supplier_is_transporter &&
			cint(frm.doc.custom_supplier_is_transporter)
		) {
			frm.set_value("custom_supplier_is_transporter", 0);
		}
		toggle_transporter_share_fields(frm);
		add_share_with_transporter_button(frm);
		return;
	}
	frappe.db.get_value("Supplier", frm.doc.supplier, "is_transporter", (r) => {
		const is_transporter = cint(r && r.is_transporter);
		frm._cgm_supplier_is_transporter = is_transporter;
		if (
			frm.doc.docstatus === 0 &&
			frm.fields_dict.custom_supplier_is_transporter &&
			cint(frm.doc.custom_supplier_is_transporter) !== is_transporter
		) {
			frm.set_value("custom_supplier_is_transporter", is_transporter);
		}
		toggle_transporter_share_fields(frm);
		add_share_with_transporter_button(frm);
	});
}

function toggle_transporter_share_fields(frm) {
	const is_transporter = supplier_is_transporter_on_invoice(frm);
	if (frm.fields_dict.custom_share_with_transporter) {
		frm.toggle_display("custom_share_with_transporter", is_transporter);
	}
	if (frm.fields_dict.custom_shared_with_transporter_on) {
		frm.toggle_display(
			"custom_shared_with_transporter_on",
			is_transporter && cint(frm.doc.custom_share_with_transporter)
		);
	}
}

function add_share_with_transporter_button(frm) {
	if (!frm.fields_dict.custom_share_with_transporter) {
		return;
	}
	if (frm.doc.docstatus !== 1 || frm.doc.is_return) {
		return;
	}
	if (!supplier_is_transporter_on_invoice(frm)) {
		return;
	}

	if (cint(frm.doc.custom_share_with_transporter)) {
		frm.dashboard.set_headline_alert(
			__("Shared with the transporter portal. They can see what CGM owes on this invoice."),
			"blue"
		);
		return;
	}

	frm.add_custom_button(__("Share with Transporter"), () => {
		frappe.confirm(
			__(
				"Share this invoice on the transporter portal? They will see that CGM owes {0}. When you record payment, they will see it as Paid.",
				[format_currency(frm.doc.outstanding_amount || frm.doc.grand_total, frm.doc.currency)]
			),
			() => share_purchase_invoice_with_transporter(frm)
		);
	}, __("CGM"));
	frm.page.set_inner_btn_group_as_primary(__("CGM"));
}

function share_purchase_invoice_with_transporter(frm) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.transporter_invoice_share.share_purchase_invoice_with_transporter",
		args: { purchase_invoice: frm.doc.name },
		freeze: true,
		freeze_message: __("Sharing with transporter…"),
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			frappe.show_alert({
				message: __("Invoice shared. The transporter can now see what CGM owes them."),
				indicator: "green",
			});
			frm.reload_doc();
		},
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
