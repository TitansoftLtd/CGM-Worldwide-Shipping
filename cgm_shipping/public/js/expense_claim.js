// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.provide("cgm.per_diem");

const PER_DIEM_TYPE = "Per Diem";

cgm.per_diem.fetch_rate = function (frm) {
	if (!frm.doc.employee) {
		frm._per_diem_rate = 0;
		return Promise.resolve(0);
	}
	if (frm._per_diem_employee === frm.doc.employee) {
		return Promise.resolve(frm._per_diem_rate || 0);
	}
	return frappe
		.call({
			method: "cgm_shipping.cgm_worldwide_shipping.customizations.per_diem.get_per_diem_details",
			args: { employee: frm.doc.employee },
		})
		.then((r) => {
			frm._per_diem_employee = frm.doc.employee;
			frm._per_diem_rate = (r.message && flt(r.message.per_diem_rate)) || 0;
			return frm._per_diem_rate;
		});
};

cgm.per_diem.price_row = function (frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row || row.expense_type !== PER_DIEM_TYPE) {
		return;
	}
	cgm.per_diem.fetch_rate(frm).then((rate) => {
		if (!rate) {
			frappe.show_alert({
				message: __("No per diem rate is set for this employee's job group. Ask HR."),
				indicator: "orange",
			});
			return;
		}
		frappe.model.set_value(cdt, cdn, "custom_per_diem_rate", rate);
		frappe.model.set_value(cdt, cdn, "amount", flt(row.custom_per_diem_days) * rate);
	});
};

frappe.ui.form.on("Expense Claim", {
	employee(frm) {
		frm._per_diem_employee = null;
		(frm.doc.expenses || []).forEach((row) => {
			if (row.expense_type === PER_DIEM_TYPE) {
				cgm.per_diem.price_row(frm, row.doctype, row.name);
			}
		});
	},
});

frappe.ui.form.on("Expense Claim Detail", {
	expense_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.expense_type !== PER_DIEM_TYPE) {
			frappe.model.set_value(cdt, cdn, "custom_per_diem_days", 0);
			frappe.model.set_value(cdt, cdn, "custom_per_diem_rate", 0);
			return;
		}
		cgm.per_diem.price_row(frm, cdt, cdn);
	},

	custom_per_diem_days(frm, cdt, cdn) {
		cgm.per_diem.price_row(frm, cdt, cdn);
	},
});
