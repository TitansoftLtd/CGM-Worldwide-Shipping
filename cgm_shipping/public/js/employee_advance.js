// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("Employee Advance", {
	onload(frm) {
		frm.set_df_property(
			"advance_account",
			"description",
			__("Cash given for this request. Receivable, not salary deduction.")
		);
	},

	refresh(frm) {
		if (frm.doc.custom_funding_request) {
			frm.set_df_property("repay_unclaimed_amount_from_salary", "hidden", 1);
			if (frm.doc.docstatus === 0 && cint(frm.doc.repay_unclaimed_amount_from_salary)) {
				frm.set_value("repay_unclaimed_amount_from_salary", 0);
			}
		}
		if (frm.doc.docstatus !== 0 || !frm.doc.advance_account) {
			return;
		}
		frappe.db.get_value("Account", frm.doc.advance_account, "account_type", (r) => {
			if (r && r.account_type && r.account_type !== "Receivable") {
				frm.set_value("advance_account", "");
			}
		});
	},

	custom_material_request(frm) {
		if (!frm.doc.custom_material_request) {
			return;
		}
		frappe.call({
			method: "cgm_shipping.cgm_worldwide_shipping.customizations.funding.get_material_request_details",
			args: { material_request: frm.doc.custom_material_request },
			callback(r) {
				if (!r.message) {
					return;
				}
				const details = r.message;
				if (!frm.doc.employee && details.employee) {
					frm.set_value("employee", details.employee);
				}
				if (!frm.doc.custom_funding_request && details.material_request) {
					frappe.db.get_value(
						"Material Request",
						frm.doc.custom_material_request,
						["custom_funding_request", "custom_approved_amount", "custom_project"],
						(vals) => {
							if (!vals) {
								return;
							}
							if (vals.custom_funding_request) {
								frm.set_value("custom_funding_request", vals.custom_funding_request);
							}
							if (vals.custom_project) {
								frm.set_value("custom_project", vals.custom_project);
							}
							if (!flt(frm.doc.advance_amount) && flt(vals.custom_approved_amount)) {
								frm.set_value("advance_amount", vals.custom_approved_amount);
							}
						}
					);
				}
				if (!frm.doc.purpose) {
					frm.set_value(
						"purpose",
						[details.item_summary, details.description].filter(Boolean).join(" — ")
					);
				}
				if (!frm.doc.custom_project && details.project) {
					frm.set_value("custom_project", details.project);
				}
			},
		});
	},
});
