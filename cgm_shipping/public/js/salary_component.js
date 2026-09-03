// "Include in Net Pay Only" - reimbursements and other pass-through payments.
//
// The rule is enforced server-side in
// cgm_shipping/cgm_worldwide_shipping/overrides/salary_component.py; this only
// makes the implied flags visible on the form as soon as the box is ticked,
// instead of after the save round-trip.

frappe.ui.form.on("Salary Component", {
	custom_include_in_net_pay_only(frm) {
		if (!frm.doc.custom_include_in_net_pay_only) {
			// Ticking this turned Do Not Include in Total on, so unticking turns it
			// back off - the component returns to Gross Pay, which is stock
			// behaviour. Re-tick it by hand if it was wanted on its own merit.
			if (frm.doc.do_not_include_in_total) {
				frm.set_value("do_not_include_in_total", 0);
				frappe.show_alert({
					message: __("Do Not Include in Total disabled, so this counts towards Gross Pay again."),
					indicator: "blue",
				});
			}
			return;
		}

		if (frm.doc.type !== "Earning") {
			frm.set_value("custom_include_in_net_pay_only", 0);
			frappe.msgprint({
				title: __("Invalid Salary Component"),
				message: __("Include in Net Pay Only can only be set on Earning components."),
				indicator: "red",
			});
			return;
		}

		if (frm.doc.statistical_component) {
			frm.set_value("custom_include_in_net_pay_only", 0);
			frappe.msgprint({
				title: __("Invalid Salary Component"),
				message: __(
					"Include in Net Pay Only cannot be used with Statistical Component: a statistical component is never paid out, so it has nothing to add to Net Pay."
				),
				indicator: "red",
			});
			return;
		}

		if (frm.doc.do_not_include_in_accounts) {
			frm.set_value("custom_include_in_net_pay_only", 0);
			frappe.msgprint({
				title: __("Invalid Salary Component"),
				message: __(
					"Include in Net Pay Only cannot be used with Do Not Include in Accounts: the component would be added to Net Pay but left out of the payroll Journal Entry and bank entry, so the payment would never be booked or paid."
				),
				indicator: "red",
			});
			return;
		}

		// The point of the flag is to keep the component out of Gross Pay, which
		// is what Do Not Include in Total does. Tick it here so the form matches
		// what the server will save.
		if (!frm.doc.do_not_include_in_total) {
			frm.set_value("do_not_include_in_total", 1);
			frappe.show_alert({
				message: __("Do Not Include in Total enabled, so this stays out of Gross Pay."),
				indicator: "blue",
			});
		}
	},

	do_not_include_in_total(frm) {
		// Unticking it would silently put the component back into Gross Pay.
		if (frm.doc.custom_include_in_net_pay_only && !frm.doc.do_not_include_in_total) {
			frm.set_value("do_not_include_in_total", 1);
			frappe.show_alert({
				message: __(
					"Do Not Include in Total is required while Include in Net Pay Only is set."
				),
				indicator: "orange",
			});
		}
	},
});
